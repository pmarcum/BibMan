#!/usr/bin/env python3
"""
BibMan USearch Index Rebuild
==============================
Rebuilds the USearch HNSW index from embeddings stored in vec_passages.
No Gemini API calls needed — uses existing embeddings from the DB.

CRITICAL ARCHITECTURAL CONSTRAINTS:
- Hardware: GCP e2-micro, 1GB RAM. Index MUST stay under ~500MB.
- Quantization: int8 ONLY. Never float16 (would exceed RAM, crash instance).
- Dimensions: 768 (truncated from 3072 via MRL). Never increase.
- Keys: MUST use search_id (64-bit fingerprint from UUID), NOT sequential ints.
  search_id = int(uuid_hex[:16], 16) & 0x7FFFFFFFFFFFFFFF
  The server queries USearch by search_id to map results back to passages.
  Using sequential keys would silently corrupt all semantic search results.

Performance optimization: fetch passage_id→search_id mapping from the regular
passages table first (fast, no vec0), then stream vec_passages separately
(no JOIN overhead on the virtual table).

Setup (monthly cron at 4am Pacific = 11am UTC on 1st of month):
  0 11 1 * * /home/bibman/bibman/venv/bin/python3 /home/bibman/bibman/bibman_rebuild_usearch.py >> /home/bibman/bibman_usearch_rebuild.log 2>&1

Usage:
  python3 bibman_rebuild_usearch.py           # full rebuild
  python3 bibman_rebuild_usearch.py --dry-run # show stats only
"""

import os
import sys
import struct
import sqlite3
import logging
import subprocess
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH     = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
BIBMAN_DIR  = Path(__file__).parent
INDEX_PATH  = BIBMAN_DIR / 'bibman_768_i8.usearch'
TS_PATH     = BIBMAN_DIR / 'bibman_768.usearch.timestamp'
VEC_SO_PATH = BIBMAN_DIR / 'vec0.so'
FULL_DIMS   = 3072   # Gemini embedding-001 output dimensions
TARGET_DIMS = 768    # MRL truncation — NEVER increase (RAM constraint)
FETCH_SIZE  = 500    # rows per fetchmany() call

DRY_RUN = '--dry-run' in sys.argv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('bibman_usearch_rebuild')


def main():
    start = datetime.now()
    log.info(f'=== USearch rebuild starting: {start.strftime("%Y-%m-%d %H:%M:%S")} ===')
    log.info(f'Database:   {DB_PATH}')
    log.info(f'Index path: {INDEX_PATH}')
    log.info(f'Mode:       {"DRY RUN" if DRY_RUN else "FULL REBUILD"}')
    log.info(f'Quantization: int8, {TARGET_DIMS}-dim (RAM-safe for e2-micro)')

    if not DB_PATH.exists():
        log.error(f'Database not found: {DB_PATH}')
        sys.exit(1)

    if not VEC_SO_PATH.exists():
        log.error(f'vec0.so not found at {VEC_SO_PATH}')
        sys.exit(1)

    # ── Step 1: Load search_id mapping from regular passages table ────────────
    # This is fast — regular table, no vec0 extension needed.
    # Build a dict: passage_id (UUID string) → search_id (int)
    log.info('Loading passage_id → search_id mapping from passages table...')
    conn_plain = sqlite3.connect(str(DB_PATH), timeout=60)
    conn_plain.execute('PRAGMA journal_mode = WAL')

    cols = [r[1] for r in conn_plain.execute('PRAGMA table_info(passages)').fetchall()]
    if 'search_id' not in cols:
        log.error('passages.search_id column not found — cannot build index')
        conn_plain.close()
        sys.exit(1)

    id_to_search_id = dict(conn_plain.execute(
        'SELECT id, search_id FROM passages WHERE search_id IS NOT NULL'
    ).fetchall())
    conn_plain.close()

    total_passages = len(id_to_search_id)
    log.info(f'Loaded {total_passages:,} passage → search_id mappings')

    if DRY_RUN:
        # Show sample to verify search_id values
        sample = list(id_to_search_id.items())[:3]
        log.info('Sample search_id values:')
        for pid, sid in sample:
            log.info(f'  passage={pid[:8]}... search_id={sid}')
        # Also count embeddings
        conn_vec = sqlite3.connect(str(DB_PATH), timeout=60)
        conn_vec.enable_load_extension(True)
        conn_vec.load_extension(str(VEC_SO_PATH))
        conn_vec.enable_load_extension(False)
        total_emb = conn_vec.execute(
            'SELECT COUNT(*) FROM vec_passages_rowids'
        ).fetchone()[0]
        conn_vec.close()
        log.info(f'Total embeddings in vec_passages: {total_emb:,}')
        log.info(f'Passages without search_id (will be skipped): {total_emb - total_passages:,}')
        log.info('Dry run complete — no changes made.')
        return

    # ── Step 2: Open vec connection and count embeddings ─────────────────────
    log.info('Opening vec_passages connection...')
    conn_vec = sqlite3.connect(str(DB_PATH), timeout=60)
    conn_vec.execute('PRAGMA journal_mode = WAL')
    try:
        conn_vec.enable_load_extension(True)
        conn_vec.load_extension(str(VEC_SO_PATH))
        conn_vec.enable_load_extension(False)
        log.info('vec0 extension loaded successfully')
    except Exception as e:
        log.error(f'Failed to load vec0: {e}')
        conn_vec.close()
        sys.exit(1)

    total_emb = conn_vec.execute(
        'SELECT COUNT(*) FROM vec_passages_rowids'
    ).fetchone()[0]
    log.info(f'Total embeddings to process: {total_emb:,}')

    if total_emb == 0:
        log.error('No embeddings found — nothing to build')
        conn_vec.close()
        sys.exit(1)

    # ── Step 3: Import dependencies ───────────────────────────────────────────
    try:
        from usearch.index import Index
        import numpy as np
    except ImportError as e:
        log.error(f'Required package not installed: {e}')
        conn_vec.close()
        sys.exit(1)

    # ── Step 4: Create USearch index ─────────────────────────────────────────
    # MUST use i8 — f16 would use ~672MB, exceeding e2-micro physical RAM
    log.info(f'Creating {TARGET_DIMS}-dim int8 USearch index...')
    index = Index(
        ndim=TARGET_DIMS,
        dtype='i8',
        metric='cos',
        connectivity=16,
        expansion_add=128,
        expansion_search=8,
    )

    # ── Step 5: Stream vec_passages and add to index ──────────────────────────
    # No JOIN here — look up search_id from the pre-loaded dictionary.
    # This avoids the slow virtual table JOIN that took ~68s for 3 rows.
    log.info('Streaming embeddings from vec_passages...')
    cursor = conn_vec.execute(
        'SELECT passage_id, embedding FROM vec_passages ORDER BY rowid'
    )

    added        = 0
    errors       = 0
    skipped_null = 0

    while True:
        rows = cursor.fetchmany(FETCH_SIZE)
        if not rows:
            break

        for passage_id, raw_bytes in rows:
            # Look up search_id from pre-loaded dict (O(1), no DB query)
            search_id = id_to_search_id.get(passage_id)
            if search_id is None:
                skipped_null += 1
                continue

            try:
                n_floats = len(raw_bytes) // 4
                full_vec = struct.unpack(f'{n_floats}f', raw_bytes)

                # Truncate to 768 dims (MRL — first N dims are meaningful)
                vec_768 = np.array(full_vec[:TARGET_DIMS], dtype=np.float32)

                # Normalize then quantize to int8 [-127, 127]
                norm = np.linalg.norm(vec_768)
                if norm > 0:
                    vec_768 = vec_768 / norm
                vec_i8 = np.clip(vec_768 * 127, -127, 127).astype(np.int8)

                # CRITICAL: use search_id as key, not a sequential integer
                index.add(key=search_id, vector=vec_i8)
                added += 1

            except Exception as e:
                log.warning(f'Failed passage {passage_id} (search_id={search_id}): {e}')
                errors += 1

        if added % 20000 == 0 and added > 0:
            pct = added / total_emb * 100
            log.info(f'  Progress: {added:,}/{total_emb:,} ({pct:.0f}%)')

    conn_vec.close()

    if skipped_null > 0:
        log.warning(f'Skipped {skipped_null} embeddings with no matching search_id')
    log.info(f'Index built: {added:,} vectors added, {errors} errors')

    if added == 0:
        log.error('No vectors added — aborting, index not saved')
        sys.exit(1)

    # ── Step 6: Save index atomically ────────────────────────────────────────
    tmp_path = INDEX_PATH.with_suffix('.usearch.tmp')
    log.info(f'Saving index to {INDEX_PATH}...')
    index.save(str(tmp_path))
    tmp_path.rename(INDEX_PATH)
    size_mb = INDEX_PATH.stat().st_size / 1024 / 1024
    log.info(f'Index saved: {size_mb:.1f} MB')

    if size_mb > 500:
        log.warning(f'WARNING: Index is {size_mb:.0f}MB — approaching e2-micro RAM limit!')

    # ── Step 7: Update timestamp ──────────────────────────────────────────────
    ts = datetime.utcnow().strftime('%a %b %d %H:%M:%S UTC %Y')
    TS_PATH.write_text(ts)
    log.info(f'Timestamp: {ts}')

    # ── Step 8: Restart bibman ────────────────────────────────────────────────
    log.info('Restarting bibman to load new index...')
    r = subprocess.run(['sudo', 'systemctl', 'restart', 'bibman'],
                       capture_output=True)
    if r.returncode == 0:
        log.info('bibman restarted successfully')
    else:
        log.warning(f'Restart failed: {r.stderr.decode()}')
        log.warning('Run manually: sudo systemctl restart bibman')

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f'=== USearch rebuild complete in {elapsed:.0f}s: {added:,} vectors ===')


if __name__ == '__main__':
    main()
