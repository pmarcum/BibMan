#!/usr/bin/env python3
"""
BibMan nightly cron job
========================
Handles tasks that are too slow to run during paper ingestion:
  1. Generate semantic embeddings for passages that don't have them yet
  2. Generate synonym pairs for papers that haven't had them generated yet

This script is safe to run while BibMan is live — it processes in small
batches and releases DB locks between batches to avoid blocking user requests.

Setup:
  crontab -e
  # Run nightly at 2am:
  0 2 * * * /home/bibman/bibman/venv/bin/python3 /home/bibman/bibman/bibman_cron.py >> /home/bibman/bibman_cron.log 2>&1

Environment:
  Reads GEMINI_KEY from /etc/systemd/system/bibman.service
  Reads DB_PATH from environment or uses default
"""

import os
import re
import sys
import time
import json
import struct
import sqlite3
import logging
import requests
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH     = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
SERVICE_FILE = Path('/etc/systemd/system/bibman.service')
LOG_FILE    = Path('/home/bibman/bibman_cron.log')

EMBED_MODEL    = 'models/gemini-embedding-001'
EMBED_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
BATCH_SIZE     = 20     # passages per Gemini API call
BATCH_SLEEP    = 0.7    # seconds between embedding batches
DB_SLEEP       = 0.5    # seconds between DB write batches (yields lock)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('bibman_cron')

# ── Read GEMINI_KEY from service file ─────────────────────────────────────────
def get_gemini_key() -> str:
    """Read GEMINI_KEY from bibman.service environment."""
    # First check environment variable directly
    key = os.environ.get('GEMINI_KEY', '').strip()
    if key:
        return key
    # Read from service file
    try:
        text = SERVICE_FILE.read_text()
        m = re.search(r'GEMINI_KEY=([^\s"]+)', text)
        if m:
            return m.group(1).strip()
        m = re.search(r'GEMINI_KEY="([^"]+)"', text)
        if m:
            return m.group(1).strip()
    except Exception as e:
        log.warning(f'Could not read GEMINI_KEY from service file: {e}')
    return ''

# ── DB connection ─────────────────────────────────────────────────────────────
def get_conn(load_vec=False):
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    if load_vec:
        so_path = Path('/home/bibman/bibman/vec0.so')
        if so_path.exists():
            try:
                conn.enable_load_extension(True)
                conn.load_extension(str(so_path))
                conn.enable_load_extension(False)
            except Exception as e:
                log.warning(f'vec0 load failed: {e}')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row
    return conn

# ── Embedding generation ──────────────────────────────────────────────────────
def embed_batch(texts: list, gemini_key: str) -> list:
    """Embed a batch of texts. Returns list of (idx, vector_bytes)."""
    url = f'{EMBED_BASE_URL}/{EMBED_MODEL}:batchEmbedContents'
    payload = {'requests': [
        {'model': EMBED_MODEL,
         'content': {'parts': [{'text': t}]},
         'taskType': 'RETRIEVAL_DOCUMENT'}
        for t in texts
    ]}
    try:
        r = requests.post(url, headers={'x-goog-api-key': gemini_key}, json=payload, timeout=60)
        r.raise_for_status()
        embeddings = r.json()['embeddings']
        results = []
        for i, emb in enumerate(embeddings):
            vec = emb['values']
            results.append((i, struct.pack(f'{len(vec)}f', *vec)))
        return results
    except Exception as e:
        log.warning(f'Embedding batch failed: {e}')
        return []

def process_embeddings(gemini_key: str) -> int:
    """
    Find passages without embeddings and generate them.
    Processes in batches, releasing DB lock between batches.
    Returns number of passages embedded.
    """
    if not gemini_key:
        log.warning('No GEMINI_KEY — skipping embedding generation')
        return 0

    conn = get_conn()

    # Find passages that have no embedding yet
    # Use a subquery since vec_passages is a virtual table
    try:
        rows = conn.execute('''
            SELECT pa.id, pa.text, pp.bibcode
            FROM passages pa
            JOIN papers pp ON pp.id = pa.paper_id
            WHERE pa.text IS NOT NULL
              AND pa.id NOT IN (SELECT id FROM vec_passages_rowids)
            ORDER BY pp.bibcode, pa.passage_index
            LIMIT 5000
        ''').fetchall()
    except Exception as e:
        log.error(f'Could not query passages: {e}')
        conn.close()
        return 0

    conn.close()

    if not rows:
        log.info('No passages need embedding — all up to date')
        return 0

    log.info(f'Found {len(rows)} passages needing embeddings')
    total_embedded = 0

    # Process in batches
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        texts = [r['text'] or '' for r in batch]
        ids   = [r['id'] for r in batch]

        vectors = embed_batch(texts, gemini_key)
        if not vectors:
            continue

        # Write embeddings to DB
        try:
            conn = get_conn(load_vec=True)
            for idx, vec_bytes in vectors:
                try:
                    conn.execute(
                        'INSERT OR IGNORE INTO vec_passages (passage_id, embedding) VALUES (?,?)',
                        (ids[idx], vec_bytes)
                    )
                except Exception as e:
                    log.warning(f'vec_passages insert failed for {ids[idx]}: {e}')
            conn.commit()
            conn.close()
            total_embedded += len(vectors)
        except Exception as e:
            log.warning(f'DB write failed for embedding batch: {e}')
            try:
                conn.close()
            except Exception:
                pass

        time.sleep(BATCH_SLEEP)

        # Progress log every 100 passages
        if (i + BATCH_SIZE) % 100 == 0:
            log.info(f'  Embedded {min(i + BATCH_SIZE, len(rows))}/{len(rows)} passages...')

        # Yield DB lock between batches
        time.sleep(DB_SLEEP)

    log.info(f'Embedding complete: {total_embedded} passages embedded')
    return total_embedded

# ── Synonym generation ────────────────────────────────────────────────────────
def process_synonyms(gemini_key: str) -> int:
    """
    Find papers that have passages but no synonyms generated yet.
    Generates synonym pairs via Gemini for each paper.
    Returns number of papers processed.
    """
    if not gemini_key:
        log.warning('No GEMINI_KEY — skipping synonym generation')
        return 0

    conn = get_conn()

    # Papers with passages but synonyms_generated_at is NULL
    rows = conn.execute('''
        SELECT DISTINCT p.id, p.bibcode, p.library_id
        FROM papers p
        WHERE p.pdf_extracted = 1
          AND p.synonyms_generated_at IS NULL
          AND EXISTS (SELECT 1 FROM passages pa WHERE pa.paper_id = p.id)
        ORDER BY p.created_at DESC
        LIMIT 50
    ''').fetchall()
    conn.close()

    if not rows:
        log.info('No papers need synonym generation — all up to date')
        return 0

    log.info(f'Found {len(rows)} papers needing synonym generation')
    processed = 0

    for row in rows:
        paper_id   = row['id']
        bibcode    = row['bibcode'] or paper_id
        library_id = row['library_id']
        try:
            conn = get_conn()
            # Import the function from the server module
            sys.path.insert(0, str(Path(__file__).parent))
            from bibman_e2micro_server import suggest_synonyms_for_paper
            n = suggest_synonyms_for_paper(paper_id, library_id, conn, gemini_key)
            conn.close()
            if n:
                log.info(f'  {bibcode}: suggested {n} synonym pairs')
            processed += 1
        except Exception as e:
            log.warning(f'Synonym generation failed for {bibcode}: {e}')
            try:
                conn.close()
            except Exception:
                pass
        time.sleep(1)  # be gentle with Gemini API

    log.info(f'Synonym generation complete: {processed} papers processed')
    return processed

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    start = datetime.now()
    log.info(f'=== BibMan cron job starting: {start.strftime("%Y-%m-%d %H:%M:%S")} ===')

    if not DB_PATH.exists():
        log.error(f'Database not found at {DB_PATH}')
        sys.exit(1)

    gemini_key = get_gemini_key()
    if not gemini_key:
        log.error('GEMINI_KEY not found — cannot generate embeddings or synonyms')
        log.error('Set GEMINI_KEY in /etc/systemd/system/bibman.service')
        sys.exit(1)

    log.info(f'Database: {DB_PATH}')
    log.info(f'Gemini key: ...{gemini_key[-6:]}')

    # Step 1: Generate embeddings
    log.info('--- Step 1: Generating embeddings ---')
    embedded = process_embeddings(gemini_key)

    # Step 2: Generate synonyms
    log.info('--- Step 2: Generating synonyms ---')
    synonyms = process_synonyms(gemini_key)

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f'=== Cron job complete in {elapsed:.0f}s: {embedded} embeddings, {synonyms} synonym papers ===')

if __name__ == '__main__':
    main()
