"""
BibMan 2.0 — E2-micro Server
==============================
Flask backend for GCE e2-micro VM.

Architecture:
  - Runs on localhost:8081 (Nginx reverse proxy handles external HTTPS on 8080/443)
  - SQLite DB lives permanently on local disk (no R2 sync)
  - All writes go directly to disk — no Save button, no dirty state
  - GAS proxy shield handles all browser traffic
  - Bookmarklet posts directly via /api/papers/add-direct
  - GooTeX calls /get_bib on localhost for bibliography export

Environment variables (set in /etc/systemd/system/bibman.service):
  DB_PATH          — absolute path to bibman.db (default: /home/bibman/bibman.db)
  LIBRARY_NAME     — default library name (default: Extragalactic)
  (ADS_TOKEN and GEMINI_KEY are NOT stored on the VM — BYOK architecture.
   They are passed per-request via X-ADS-Token and X-Gemini-Key headers.)
  SESSION_SECRET   — random hex string for session signing
  GAS_CREDENTIAL   — shared secret for GAS proxy auth (generate: openssl rand -hex 16)
                     Required: the server refuses to start without one (16+ characters).
  EXPORT_CREDENTIAL — optional read-only key accepted ONLY on the bibliography-export routes
                     (/api/export/bib, /api/export/bib-text, /api/libraries/<name>/stats); give
                     this to gooTeX instead of GAS_CREDENTIAL (generate: openssl rand -hex 16)

Setup:
  pip install flask flask-cors requests pypdf pdfminer.six pymupdf sqlite-vec
  apt-get install -y poppler-utils
"""

import os
import io
import re
import json
import uuid
import sqlite3
import struct
import logging
import threading
import time
import base64
import hmac
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps
from collections import Counter

import numpy as np
import requests
from flask import Flask, jsonify, request, Response, session, has_request_context
from flask_cors import CORS

# ── Astronomy text normalisation ──────────────────────────────────────────────
try:
    from bibman_normalize import normalize_for_db
except ImportError:
    def normalize_for_db(term):
        return re.sub(r'\s+', ' ', term.lower().strip())

# ── AASTeX Journal Macros ─────────────────────────────────────────────────────

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH        = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
LIBRARY_NAME   = os.environ.get('LIBRARY_NAME', 'Extragalactic')

# ADS_TOKEN and GEMINI_KEY are NOT stored on VM — extracted per-request from headers
SESSION_SECRET = os.environ.get('SESSION_SECRET', os.urandom(24).hex())
GAS_CREDENTIAL = os.environ.get('GAS_CREDENTIAL', '')  # shared secret for GAS proxy
# Optional read-only key for the bibliography-export routes only (what gooTeX uses). Unset = not accepted.
EXPORT_CREDENTIAL = os.environ.get('EXPORT_CREDENTIAL', '')
if len(GAS_CREDENTIAL) < 16:
    # Without a credential every route would be open to anyone who can reach nginx: refuse to start instead.
    raise SystemExit('BibMan: GAS_CREDENTIAL is missing or shorter than 16 characters; refusing to start. '
                     'Set it in /etc/systemd/system/bibman.service (openssl rand -hex 16).')
PORT           = int(os.environ.get('PORT', 8081))
PDF_FOLDER_ID  = os.environ.get('PDF_FOLDER_ID', '')   # Drive folder for auto-saved PDFs
CHUNK_WORDS    = 150
CHUNK_OVERLAP  = 30

# ── Flask app ─────────────────────────────────────────────────────────────────
APP_DIR = Path(__file__).parent
app = Flask(__name__)
app.secret_key = SESSION_SECRET
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 30
CORS(app, supports_credentials=True)
from flask_compress import Compress
Compress(app)

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('bibman')

# ── sqlite-vec ────────────────────────────────────────────────────────────────
def _find_sqlite_vec() -> Path:
    import platform
    system  = platform.system()
    machine = platform.machine()
    names = {
        ('Linux',  'x86_64'): 'vec0-linux-x86_64.so',
        ('Darwin', 'x86_64'): 'vec0-macos-x86_64.dylib',
        ('Darwin', 'arm64'):  'vec0-macos-aarch64.dylib',
    }
    filename  = names.get((system, machine), 'vec0.so')
    candidate = APP_DIR / filename
    if candidate.exists():
        return candidate
    # Try sqlite_vec Python package
    try:
        import sqlite_vec as _sv
        return Path(_sv.__file__).parent / filename
    except Exception:
        pass
    return APP_DIR / 'vec0.so'

SQLITE_VEC_SO = _find_sqlite_vec()

# Test if sqlite-vec actually works at startup
def _test_vec_available() -> bool:
    try:
        import sqlite3 as _sq
        c = _sq.connect(':memory:')
        c.enable_load_extension(True)
        try:
            import sqlite_vec as _sv
            _sv.load(c)
        except Exception:
            if SQLITE_VEC_SO.exists():
                c.load_extension(str(SQLITE_VEC_SO))
            else:
                return False
        c.execute("SELECT vec_version()")
        c.close()
        return True
    except Exception:
        return False

VEC_AVAILABLE = _test_vec_available()
log.info(f'sqlite-vec available: {VEC_AVAILABLE}')

# ── USearch HNSW Index (loaded once at startup) ───────────────────────────────
USEARCH_INDEX = None
USEARCH_TIMESTAMP = None
USEARCH_PATH = DB_PATH.parent / 'bibman_768_i8.usearch'
USEARCH_TIMESTAMP_PATH = DB_PATH.parent / 'bibman_768.usearch.timestamp'

def _load_usearch_index():
    """Load USearch index once at module import time."""
    global USEARCH_INDEX, USEARCH_TIMESTAMP
    try:
        from usearch.index import Index
        if USEARCH_PATH.exists():
            # Index is int8 quantized (336MB) to fit in e2-micro RAM
            USEARCH_INDEX = Index.restore(str(USEARCH_PATH), view=True)
            # Reduce expansion_search for faster queries on e2-micro (trade accuracy for speed)
            USEARCH_INDEX.expansion_search = 8
            log.info(f'USearch index loaded: {USEARCH_INDEX.size} vectors, {USEARCH_INDEX.ndim} dims, expansion={USEARCH_INDEX.expansion_search}')
            if USEARCH_TIMESTAMP_PATH.exists():
                USEARCH_TIMESTAMP = USEARCH_TIMESTAMP_PATH.read_text().strip()
                log.info(f'USearch index timestamp: {USEARCH_TIMESTAMP}')
        else:
            log.warning(f'USearch index not found at {USEARCH_PATH}')
    except Exception as e:
        log.warning(f'USearch not available: {e}')

_load_usearch_index()
if EXPORT_CREDENTIAL and len(EXPORT_CREDENTIAL) < 16:
    log.warning('EXPORT_CREDENTIAL is set but shorter than 16 characters; it will NOT be accepted.')

# ── CONFIG dict (runtime settings, persisted as JSON next to DB) ──────────────
CONFIG_PATH = DB_PATH.parent / 'bibman_config.json'

def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text())
    except Exception:
        pass
    return {}

def save_config(cfg: dict):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
    except Exception as e:
        log.warning(f'save_config failed: {e}')

CONFIG = {
    'library_name': LIBRARY_NAME,
    # ads_token and gemini_key intentionally absent — BYOK, passed per-request
    'username':     '',
    **load_config(),
}

def update_gas_webapp_url():
    """Persist GAS webapp URL from request header — self-updates when URL changes."""
    url = request.headers.get('X-GAS-Webapp-URL', '').strip()
    if url and url != CONFIG.get('gas_webapp_url', ''):
        CONFIG['gas_webapp_url'] = url
        save_config(CONFIG)
        log.info(f'GAS webapp URL updated in config: {url}')

# ── DB connection ─────────────────────────────────────────────────────────────
def get_db_connection():
    """Open a WAL-mode SQLite connection with sqlite-vec loaded."""
    if not DB_PATH.exists():
        raise RuntimeError(f'Database not found at {DB_PATH}')
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    # Load sqlite-vec
    try:
        import sqlite_vec as _sv
        conn.enable_load_extension(True)
        _sv.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        if SQLITE_VEC_SO.exists():
            try:
                conn.enable_load_extension(True)
                conn.load_extension(str(SQLITE_VEC_SO))
                conn.enable_load_extension(False)
            except Exception as e:
                log.debug(f'sqlite-vec load failed: {e}')
    conn.execute('PRAGMA journal_mode = WAL')
    conn.execute('PRAGMA foreign_keys = ON')
    conn.row_factory = sqlite3.Row
    try:
        _ensure_columns(conn)
    except Exception as e:
        log.warning(f'Schema migration warning: {e}')
    return conn

def get_current_library_id(conn=None):
    """Return (library_id, library_name) for the current library."""
    close = False
    if conn is None:
        conn  = get_db_connection()
        close = True
    try:
        lib_name = CONFIG.get('library_name') or LIBRARY_NAME
        row = conn.execute(
            'SELECT id, name FROM libraries WHERE name = ?', (lib_name,)
        ).fetchone()
        if row:
            return row['id'], row['name']
        # Fallback to first library
        row = conn.execute('SELECT id, name FROM libraries LIMIT 1').fetchone()
        if row:
            return row['id'], row['name']
        return None, None
    finally:
        if close:
            conn.close()

def err(msg, code=400):
    return jsonify({'error': msg}), code

# ── Auth: GAS credential validation ──────────────────────────────────────────
def check_gas_credential(credential: str) -> bool:
    """
    Validate the GAS proxy credential.
    The GAS proxy injects GAS_CREDENTIAL into every request header.
    This prevents direct access to the ngrok URL bypassing GAS.
    """
    return isinstance(credential, str) and bool(credential) and hmac.compare_digest(credential.encode(), GAS_CREDENTIAL.encode())

def check_export_credential(credential: str) -> bool:
    """True for the read-only EXPORT_CREDENTIAL (only if one is configured and at least 16 characters)."""
    return (len(EXPORT_CREDENTIAL) >= 16 and isinstance(credential, str) and bool(credential)
            and hmac.compare_digest(credential.encode(), EXPORT_CREDENTIAL.encode()))

def gas_auth_required(f):
    """
    Decorator for routes called by GAS proxy.
    Checks X-BibMan-Credential header or 'credential' in JSON body.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check header first (preferred)
        cred = request.headers.get('X-BibMan-Credential', '')
        # Fall back to JSON body
        if not cred and request.is_json:
            cred = (request.json or {}).get('credential', '')
        if not check_gas_credential(cred):
            return err('Unauthorized', 401)
        update_gas_webapp_url()
        return f(*args, **kwargs)
    return decorated

def export_auth_required(f):
    """
    Decorator for the bibliography-export routes that gooTeX calls (/api/export/bib,
    /api/export/bib-text, /api/libraries/<name>/stats). Accepts the full GAS_CREDENTIAL
    or the read-only EXPORT_CREDENTIAL. Every other route accepts GAS_CREDENTIAL only.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        cred = request.headers.get('X-BibMan-Credential', '')
        if not cred and request.is_json:
            cred = (request.json or {}).get('credential', '')
        if check_gas_credential(cred):
            update_gas_webapp_url()
            return f(*args, **kwargs)
        if check_export_credential(cred):
            return f(*args, **kwargs)
        return err('Unauthorized', 401)
    return decorated

def get_request_tokens():
    """
    Extract caller-supplied API keys from request headers.
    Keys are held in memory only for the duration of this request.
    Never logged, never written to disk or DB.
    Returns (ads_token, gemini_key) as strings (empty string if absent).
    """
    ads_token  = request.headers.get('X-ADS-Token',    '').strip()
    gemini_key = request.headers.get('X-Gemini-Key',   '').strip()
    return ads_token, gemini_key

def get_request_models() -> tuple:
    """Extract model names from request headers, falling back to module constants."""
    if not has_request_context():  # background threads (nightly job, ingest) have no request
        return EMBED_MODEL, 'models/gemini-2.0-flash'
    embed_model    = request.headers.get('X-Embed-Model',    '').strip() or EMBED_MODEL
    generate_model = request.headers.get('X-Generate-Model', '').strip() or 'models/gemini-2.0-flash'
    return embed_model, generate_model


def get_user_id() -> str:
    """Extract user identifier from request."""
    try:
        body = request.get_json(silent=True) or {}
        if body.get('_username'):
            return body['_username']
    except Exception:
        pass
    u = request.args.get('_u', '')
    if u: return u
    email = request.headers.get('X-BibMan-User', 'user')
    return email.split('@')[0] if '@' in email else email

# ── Schema migrations ─────────────────────────────────────────────────────────
def _ensure_columns(conn):
    migrations = [
        # papers
        ('papers', 'pdf_url',            'TEXT'),
        ('papers', 'key_paper',           'INTEGER DEFAULT 0'),
        ('papers', 'pinned',              'INTEGER DEFAULT 0'),
        ('papers', 'followup',            'INTEGER DEFAULT 0'),
        ('papers', 'file_id',            'TEXT'),
        ('papers', 'pdf_extracted',      'INTEGER DEFAULT 0'),
        ('papers', 'read_status',        'TEXT DEFAULT "unread"'),
        ('papers', 'pubtype',            'TEXT DEFAULT "article"'),
        ('papers', 'bibcode',            'TEXT'),
        ('papers', 'doi',                'TEXT'),
        ('papers', 'content_source_url', 'TEXT'),
        ('papers', 'bibtex',             'TEXT'),
        ('papers', 'abstract',           'TEXT'),
        ('papers', 'added_by',           'TEXT'),
        ('papers', 'tags',               'TEXT'),
        ('papers', 'created_at',         'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        ('papers', 'updated_at',         'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        # passages
        ('passages', 'page_number',      'INTEGER DEFAULT 1'),
        ('passages', 'x1',               'REAL DEFAULT 0'),
        ('passages', 'y1',               'REAL DEFAULT 0'),
        ('passages', 'x2',               'REAL DEFAULT 1'),
        ('passages', 'y2',               'REAL DEFAULT 1'),
        ('passages', 'created_at',       'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        # annotations
        ('annotations', 'flag_key_point','INTEGER DEFAULT 0'),
        ('annotations', 'flag_follow_up','INTEGER DEFAULT 0'),
        ('annotations', 'flag_pinned',   'INTEGER DEFAULT 0'),
        ('annotations', 'created_at',    'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        ('annotations', 'updated_at',    'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        # synonyms
        ('synonyms', 'is_suspicious',    'INTEGER DEFAULT 0'),
        ('synonyms', 'notes',            'TEXT'),
        ('synonyms', 'confidence',       'REAL DEFAULT 1.0'),
        ('synonyms', 'is_suppressed',    'INTEGER DEFAULT 0'),
        ('synonyms', 'created_at',       'DATETIME DEFAULT CURRENT_TIMESTAMP'),
        # Track whether synonym generation has been run for each paper
        ('papers',   'synonyms_generated_at', 'DATETIME'),
    ]
    # Ensure vec_annotations table exists for annotation embeddings
    try:
        conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_annotations
            USING vec0(annotation_id TEXT PRIMARY KEY, embedding FLOAT[768])
        ''')
        conn.commit()
    except Exception:
        pass  # sqlite-vec not loaded or table already exists
    # Ensure annotations_fts table exists
    try:
        conn.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS annotations_fts
            USING fts5(user_note, annotation_id UNINDEXED)
        ''')
        conn.commit()
    except Exception:
        pass
    for table, col, col_type in migrations:
        try:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {col_type}')
            conn.commit()
        except Exception:
            pass  # column already exists

    # mentions table
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS mentions (
                id          TEXT PRIMARY KEY,
                paper_id    TEXT NOT NULL,
                annotation_id TEXT,
                mentioned_by  TEXT NOT NULL,
                mentioned_user TEXT NOT NULL,
                note        TEXT DEFAULT '',
                seen        INTEGER DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE
            )
        ''')
        conn.commit()
    except Exception:
        pass

    # team_members table
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS team_members (
                id         TEXT PRIMARY KEY,
                username   TEXT NOT NULL UNIQUE,
                added_by   TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
    except Exception:
        pass

    # user_tag_labels table — each user's personal label definitions
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_tag_labels (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                label      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT '#f59e0b',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, label)
            )
        ''')
        conn.commit()
    except Exception:
        pass

    # paper_tags table — tags applied to papers (and optionally annotations) by users
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS paper_tags (
                id            TEXT PRIMARY KEY,
                paper_id      TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                label_id      TEXT NOT NULL,
                annotation_id TEXT DEFAULT NULL,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                FOREIGN KEY(label_id) REFERENCES user_tag_labels(id) ON DELETE CASCADE,
                UNIQUE(paper_id, user_id, label_id, annotation_id)
            )
        ''')
        conn.commit()
    except Exception:
        pass
    # Add annotation_id column to existing paper_tags if missing
    try:
        conn.execute('ALTER TABLE paper_tags ADD COLUMN annotation_id TEXT DEFAULT NULL')
        conn.commit()
    except Exception:
        pass

# ── Text processing ───────────────────────────────────────────────────────────
_NORM_MAP = {
    '\u03B1':'alpha','\u0391':'alpha','\u03B2':'beta','\u0392':'beta',
    '\u03B3':'gamma','\u03B4':'delta','\u03B7':'eta','\u03BB':'lambda',
    '\u03BC':'mu','\u03BD':'nu','\u03C0':'pi','\u03C3':'sigma',
    '\u03C6':'phi','\u03C9':'omega','\u03B8':'theta',
    '\u2080':'0','\u2081':'1','\u2082':'2','\u2083':'3','\u2084':'4',
    '\u2085':'5','\u2086':'6','\u2087':'7','\u2088':'8','\u2089':'9',
    '\u00B2':'2','\u00B3':'3',
    '\u2013':'-','\u2014':'-','\u2212':'-',
    '\uFB01':'fi','\uFB02':'fl','\uFB00':'ff','\uFB03':'ffi','\uFB04':'ffl',
    '\u00A0':' ','\u2299':'solar','\u00B1':'+-','\u00B5':'mu',
}
_NORM_RE = re.compile('|'.join(re.escape(k) for k in _NORM_MAP))

def normalize_passage_text(text: str) -> str:
    if not text:
        return text
    text = _NORM_RE.sub(lambda m: _NORM_MAP[m.group(0)], text)
    text = re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', text)
    return text

def extract_text_from_pdf(pdf_bytes: bytes):
    """
    Extract text from PDF with per-block bounding boxes.
    Returns [(page_num, [(text, x0, y0, x1, y1)])] or None.
    Primary: PyMuPDF (real bounding boxes).
    Fallback: pdftotext, pypdf (dummy bbox 0,0,1,1).
    """
    def _clean(t):
        return re.sub(r'(\w+)-\s*\n\s*(\w+)', r'\1\2', t or '').strip()

    def _pages_to_blocks(page_list):
        return [(pn, [(_clean(pt), 0.0, 0.0, 1.0, 1.0)])
                for pn, pt in page_list if _clean(pt)]

    # Primary: PyMuPDF
    try:
        import fitz
        doc   = fitz.open(stream=pdf_bytes, filetype='pdf')
        pages = []
        for i in range(len(doc)):
            page   = doc[i]
            pw, ph = page.rect.width, page.rect.height
            if pw <= 0 or ph <= 0:
                continue
            blocks = []
            for b in page.get_text('dict')['blocks']:
                if b['type'] != 0:
                    continue
                text = ' '.join(
                    s['text'] for l in b['lines'] for s in l['spans']
                ).strip()
                text = _clean(text)
                if not text:
                    continue
                x0 = b['bbox'][0]/pw; y0 = b['bbox'][1]/ph
                x1 = b['bbox'][2]/pw; y1 = b['bbox'][3]/ph
                blocks.append((text, x0, y0, x1, y1))
            if blocks:
                pages.append((i + 1, blocks))
        doc.close()
        if pages:
            return pages
    except ImportError:
        log.warning('PyMuPDF not installed — pip install pymupdf')
    except Exception as e:
        log.warning(f'PyMuPDF failed: {e}')

    # Fallback: pdftotext
    try:
        import subprocess
        r = subprocess.run(
            ['pdftotext', '-enc', 'UTF-8', '-', '-'],
            input=pdf_bytes, capture_output=True, timeout=60
        )
        if r.returncode == 0:
            raw = r.stdout.decode('utf-8', errors='replace').split('\f')
            if raw and not raw[0].strip():
                raw = raw[1:]
            page_list = [(i+1, _clean(p)) for i, p in enumerate(raw) if _clean(p)]
            if page_list:
                return _pages_to_blocks(page_list)
    except Exception:
        pass

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader    = PdfReader(io.BytesIO(pdf_bytes))
        page_list = [(i+1, _clean(p.extract_text() or ''))
                     for i, p in enumerate(reader.pages)
                     if _clean(p.extract_text() or '')]
        if page_list:
            return _pages_to_blocks(page_list)
    except Exception:
        pass

    log.warning('All PDF extraction methods failed — image-only PDF?')
    return None

def extract_text_from_html(html) -> str | None:
    if isinstance(html, bytes):
        html = html.decode('utf-8', errors='replace')
    try:
        import trafilatura
        text = trafilatura.extract(html, include_tables=False)
        if text and len(text.split()) > 50:
            return text
    except ImportError:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script','style','nav','footer','header']):
            tag.decompose()
        text = ' '.join(soup.get_text().split())
        if text and len(text.split()) > 50:
            return text
    except ImportError:
        pass
    return None

def chunk_text(pages, paper_id: str) -> list:
    """
    Chunk extracted PDF text into overlapping word-window passages.
    pages: [(page_num, [(text, x0, y0, x1, y1)])] or legacy formats
    Returns list of passage dicts with real bounding boxes.
    """
    if isinstance(pages, str):
        page_list = [(0, [(pages, 0.0, 0.0, 1.0, 1.0)])]
    elif pages and isinstance(pages[0], tuple):
        first_val = pages[0][1]
        if isinstance(first_val, str):
            page_list = [(pn, [(pt, 0.0, 0.0, 1.0, 1.0)])
                         for pn, pt in pages if pt and pt.strip()]
        else:
            page_list = [(pn, blks) for pn, blks in pages if blks]
    else:
        page_list = []

    passages = []
    step = CHUNK_WORDS - CHUNK_OVERLAP

    for page_num, blocks in page_list:
        word_entries = []
        clean_blocks = []
        for bi, block in enumerate(blocks):
            if isinstance(block, (list, tuple)) and len(block) >= 5:
                raw_text, bx0, by0, bx1, by1 = (
                    block[0], block[1], block[2], block[3], block[4]
                )
            else:
                raw_text = str(block)
                bx0, by0, bx1, by1 = 0.0, 0.0, 1.0, 1.0
            norm_text = normalize_passage_text(raw_text)
            clean_blocks.append((bx0, by0, bx1, by1))
            for w in norm_text.split():
                word_entries.append((w, bi))

        if not word_entries:
            continue

        for i in range(0, max(1, len(word_entries) - CHUNK_OVERLAP), step):
            chunk     = word_entries[i:i + CHUNK_WORDS]
            chunk_str = ' '.join(w for w, _ in chunk)
            if len(chunk_str.strip()) < 50:
                continue
            bidxs = {bi for _, bi in chunk}
            x0 = min(clean_blocks[bi][0] for bi in bidxs)
            y0 = min(clean_blocks[bi][1] for bi in bidxs)
            x1 = max(clean_blocks[bi][2] for bi in bidxs)
            y1 = max(clean_blocks[bi][3] for bi in bidxs)
            passages.append({
                'id':            str(uuid.uuid4()),
                'paper_id':      paper_id,
                'page_number':   page_num,
                'passage_index': len(passages),
                'text':          chunk_str,
                'x1': x0, 'y1': y0, 'x2': x1, 'y2': y1,
            })
    return passages

# ── Embedding ─────────────────────────────────────────────────────────────────
EMBED_MODEL    = 'models/gemini-embedding-001'
EMBED_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

def _gemini_headers(gemini_key: str) -> dict:
    """Send the Gemini key as a header so it never appears in URLs, exception text or logs."""
    return {'x-goog-api-key': gemini_key}

def embed_passages(passages: list, gemini_key: str = '', embed_model: str = '') -> list:
    if not gemini_key:
        return []
    _embed_model = embed_model or EMBED_MODEL
    url     = f'{EMBED_BASE_URL}/{_embed_model}:batchEmbedContents'
    results = []
    batch_size = 20
    for i in range(0, len(passages), batch_size):
        batch   = passages[i:i + batch_size]
        texts   = [re.sub(r'(\w{3,})-\s*\n\s*(\w{3,})', r'\1\2',
                          p['text'] or '') for p in batch]
        payload = {'requests': [
            {'model': _embed_model,
             'content': {'parts': [{'text': t}]},
             'taskType': 'RETRIEVAL_DOCUMENT'}
            for t in texts
        ]}
        try:
            r = requests.post(url, headers=_gemini_headers(gemini_key), json=payload, timeout=60)
            r.raise_for_status()
            embeddings = [e['values'] for e in r.json()['embeddings']]
            for p, vec in zip(batch, embeddings):
                results.append((p['id'], struct.pack(f'{len(vec)}f', *vec)))
            time.sleep(0.7)
        except Exception as e:
            log.warning(f'Embedding batch {i//batch_size+1} failed: {e}')
    return results

def embed_query(text: str, gemini_key: str = '') -> bytes | None:
    if not gemini_key:
        return None
    try:
        url = f'{EMBED_BASE_URL}/{EMBED_MODEL}:embedContent'
        r   = requests.post(url, headers=_gemini_headers(gemini_key), json={
            'model':    EMBED_MODEL,
            'content':  {'parts': [{'text': text}]},
            'taskType': 'RETRIEVAL_QUERY',
        }, timeout=5)
        r.raise_for_status()
        vec = r.json()['embedding']['values']
        return struct.pack(f'{len(vec)}f', *vec)
    except Exception as e:
        log.warning(f'Query embedding failed: {e}')
        return None

# ── PDF fetching ──────────────────────────────────────────────────────────────
_BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/120.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/pdf,*/*',
}

def fetch_arxiv_pdf(arxiv_id: str) -> bytes | None:
    arxiv_id = arxiv_id.replace('arXiv:', '').strip()
    try:
        r = requests.get(f'https://arxiv.org/pdf/{arxiv_id}',
                         headers=_BROWSER_HEADERS, timeout=30, allow_redirects=True)
        if r.status_code == 200 and r.content[:4] == b'%PDF':
            return r.content
    except Exception:
        pass
    return None

def fetch_arxiv_html(arxiv_id: str) -> str | None:
    arxiv_id = re.sub(r'^arXiv:', '', arxiv_id, flags=re.I).strip()
    for url in [
        f'https://ar5iv.labs.arxiv.org/html/{arxiv_id}',
        f'https://arxiv.org/html/{arxiv_id}',
    ]:
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
            if r.status_code == 200 and len(r.text) > 5000:
                return r.text
        except Exception:
            pass
    return None

def fetch_url_content(url: str) -> tuple:
    try:
        r  = requests.get(url, headers=_BROWSER_HEADERS,
                          timeout=30, allow_redirects=True)
        ct = r.headers.get('Content-Type', '')
        if r.content[:4] == b'%PDF' or 'pdf' in ct:
            return r.content, 'pdf'
        return r.text, 'html'
    except Exception as e:
        log.debug(f'fetch_url_content {url}: {e}')
        return None, ''

def fetch_content_for_paper(paper: dict, ads_token: str = '') -> tuple:
    """
    Returns (content, source_type, source_url, no_free_pdf).
    no_free_pdf=True means paywalled (set pdf_extracted=3).
    no_free_pdf=False means transient error (set pdf_extracted=2).
    Priority: Drive file_id → pdf_url → arXiv → ADS
    """
    file_id  = (paper.get('file_id') or '').strip()
    pdf_url  = (paper.get('pdf_url') or '').strip()
    bibcode  = (paper.get('bibcode') or '').strip()
    identifiers = paper.get('identifiers') or []

    # 1. Google Drive file_id
    if file_id:
        try:
            from googleapiclient.http import MediaIoBaseDownload
            service    = get_drive_service()
            request_dr = service.files().get_media(fileId=file_id)
            buf        = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request_dr)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            candidate = buf.getvalue()
            if candidate[:4] == b'%PDF':
                return candidate, 'pdf', f'drive:{file_id}', False
        except Exception as e:
            log.warning(f'Drive fetch failed file_id={file_id}: {e}')

    # 2. Explicit pdf_url
    if pdf_url:
        content, source_type = fetch_url_content(pdf_url)
        if content:
            return content, source_type, pdf_url, False

    # 3. arXiv
    arxiv_id = None
    for ident in identifiers:
        if str(ident).lower().startswith('arxiv:'):
            arxiv_id = str(ident).split(':', 1)[1].strip()
            break
    if not arxiv_id and bibcode and 'arxiv' in bibcode.lower():
        arxiv_id = re.sub(r'^arxiv:', '', bibcode, flags=re.I).strip()
    if arxiv_id:
        pdf = fetch_arxiv_pdf(arxiv_id)
        if pdf:
            return pdf, 'pdf', f'https://arxiv.org/pdf/{arxiv_id}', False
        html = fetch_arxiv_html(arxiv_id)
        if html:
            return html, 'html', f'https://arxiv.org/abs/{arxiv_id}', False

    # 4. ADS
    if bibcode and ads_token:
        try:
            r = requests.get(
                f'https://api.adsabs.harvard.edu/v1/resolver/{bibcode}/pdf',
                headers={'Authorization': f'Bearer {ads_token}'}, timeout=20
            )
            link = r.json().get('link', '')
            if link:
                content, kind = fetch_url_content(link)
                if content and kind == 'pdf':
                    return content, 'pdf', link, False
        except Exception:
            pass

    return None, '', '', False

# ── Passage write ─────────────────────────────────────────────────────────────
def write_passages_to_db(paper_id: str, passages: list,
                          bibcode: str = '', source_url: str = '') -> bool:
    """
    Write extracted passages to DB and set pdf_extracted=1.
    Embeddings and synonyms are NOT generated here — handled by
    bibman_cron.py (nightly job) to avoid long DB locks.
    """
    if not passages:
        return False
    conn = get_db_connection()
    try:
        old_ids = [r['id'] for r in conn.execute(
            'SELECT id FROM passages WHERE paper_id = ?', (paper_id,)
        ).fetchall()]
        if old_ids:
            ph = ','.join('?' * len(old_ids))
            try:
                conn.execute(
                    f'DELETE FROM vec_passages WHERE passage_id IN ({ph})', old_ids
                )
            except Exception:
                pass
            conn.execute('DELETE FROM passages WHERE paper_id = ?', (paper_id,))
        conn.executemany('''
            INSERT OR IGNORE INTO passages
                (id, paper_id, page_number, passage_index, text, x1, y1, x2, y2)
            VALUES
                (:id,:paper_id,:page_number,:passage_index,:text,:x1,:y1,:x2,:y2)
        ''', passages)
        if source_url and source_url.startswith('https://arxiv.org/pdf/'):
            conn.execute(
                'UPDATE papers SET pdf_extracted=1, content_source_url=?, pdf_url=? WHERE id=?',
                (source_url, source_url, paper_id)
            )
        else:
            conn.execute(
                'UPDATE papers SET pdf_extracted=1, content_source_url=? WHERE id=?',
                (source_url, paper_id)
            )
        conn.commit()
        update_corpus_terms(conn, paper_id)
        return True
    except Exception as e:
        log.error(f'DB write failed for {paper_id}: {e}')
        conn.rollback()
        return False
    finally:
        conn.close()

def update_corpus_terms(conn, paper_id: str = None):
    STOP = {'the','a','an','and','or','of','in','to','is','are','was','were',
            'it','its','this','that','with','for','on','at','by','from','be',
            'been','have','has','had','not','but','as','et','al','we','our',
            'they','their','these','those','can','may','also','such','more','than'}
    try:
        if paper_id:
            row = conn.execute(
                'SELECT library_id FROM papers WHERE id=?', (paper_id,)
            ).fetchone()
            if not row:
                return
            library_id = row['library_id']
        else:
            library_id, _ = get_current_library_id(conn)
            if not library_id:
                return

        rows = conn.execute('''
            SELECT pa.text FROM passages pa
            JOIN papers pp ON pp.id = pa.paper_id
            WHERE pa.text IS NOT NULL AND pp.library_id = ?
            ORDER BY RANDOM() LIMIT 5000
        ''', (library_id,)).fetchall()

        unigrams = Counter()
        bigrams  = Counter()
        for (text,) in rows:
            words = re.findall(r'[a-z][a-z0-9-]{1,30}', (text or '').lower())
            words = [w for w in words if w not in STOP and len(w) > 2]
            unigrams.update(words)
            bigrams.update(zip(words, words[1:]))

        terms = []
        for term, freq in unigrams.most_common(3000):
            if freq >= 3:
                terms.append((str(uuid.uuid4()), library_id, term, freq, 0))
        for (a, b), freq in bigrams.most_common(2000):
            if freq >= 2:
                terms.append((str(uuid.uuid4()), library_id, f'{a} {b}', freq, 1))

        conn.executemany('''
            INSERT INTO corpus_terms (id, library_id, term, frequency, is_phrase)
            VALUES (?,?,?,?,?)
            ON CONFLICT(library_id, term) DO UPDATE SET
                frequency=excluded.frequency,
                updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
        ''', terms)
        conn.commit()
    except Exception as e:
        log.warning(f'update_corpus_terms failed: {e}')

def suggest_synonyms_for_paper(paper_id: str, library_id: str, conn,
                                gemini_key: str = '', generate_model: str = '') -> int:
    if not gemini_key:
        return 0
    rows = conn.execute(
        'SELECT text FROM passages WHERE paper_id=? ORDER BY passage_index LIMIT 30',
        (paper_id,)
    ).fetchall()
    if not rows:
        return 0
    sample_text = ' '.join(r['text'] for r in rows)[:6000]
    prompt = (
        'You are an astronomy terminology expert.\n'
        'Identify GENUINE synonym pairs from this passage — terms that mean the same thing in astronomy.\n'
        'Return ONLY a JSON array: [{"term_a":"...","term_b":"..."}, ...]\n'
        '3-20 pairs, empty array if fewer than 3 genuine pairs.\n\n'
        'STRICT RULES:\n'
        '- Only include pairs where both terms are real astronomy/physics concepts or abbreviations\n'
        '- Do NOT include figure labels, axis labels, legend text, or caption fragments\n'
        '- Do NOT include phrases like "see figure", "dashed line", "left panel", "not to scale"\n'
        '- Do NOT include partial words or sentence fragments\n'
        '- Both terms must be at least 3 characters long\n'
        '- Examples of GOOD pairs: ("AGN", "active galactic nucleus"), ("SFR", "star formation rate")\n'
        '- Examples of BAD pairs: ("AGN", "see figure 2"), ("HII", "left"), ("SFR", "dashed line")\n\n'
        f'PASSAGE:\n{sample_text}'
    )
    url = (f'https://generativelanguage.googleapis.com/v1beta/'
           f'{generate_model or get_request_models()[1]}:generateContent')
    try:
        r = requests.post(url, headers=_gemini_headers(gemini_key), json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 1024},
        }, timeout=30)
        r.raise_for_status()
        raw   = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        raw   = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.S).strip()
        pairs = json.loads(raw)
        if not isinstance(pairs, list):
            return 0
    except Exception as e:
        log.warning(f'suggest_synonyms Gemini call failed: {e}')
        return 0

    inserted = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        term_a = str(pair.get('term_a') or '').strip()
        term_b = str(pair.get('term_b') or '').strip()
        if not term_a or not term_b or term_a.lower() == term_b.lower():
            continue
        a_norm = normalize_for_db(term_a)
        b_norm = normalize_for_db(term_b)
        if not a_norm or not b_norm or a_norm == b_norm:
            continue
        existing = conn.execute(
            'SELECT id FROM synonyms WHERE library_id=? '
            'AND ((term_a_norm=? AND term_b_norm=?) OR (term_a_norm=? AND term_b_norm=?))',
            (library_id, a_norm, b_norm, b_norm, a_norm)
        ).fetchone()
        if existing:
            continue
        conn.execute(
            'INSERT INTO synonyms '
            '(id,library_id,term_a,term_b,term_a_norm,term_b_norm,source,confidence,is_suppressed)'
            ' VALUES (?,?,?,?,?,?,?,?,?)',
            (str(uuid.uuid4()), library_id, term_a, term_b, a_norm, b_norm,
             'embedding_suggested', 0.7, 1)
        )
        inserted += 1
    if inserted:
        conn.commit()
    # Always record that synonym generation was attempted for this paper
    try:
        conn.execute(
            "UPDATE papers SET synonyms_generated_at=datetime('now') WHERE id=?",
            (paper_id,)
        )
        conn.commit()
    except Exception:
        pass
    return inserted

# ── Background ingest ─────────────────────────────────────────────────────────
def embed_annotation_background(ann_id: str, text: str, paper_id: str,
                                  gemini_key: str = ''):
    """
    Generate and store embedding + FTS entry for an annotation.
    Runs in a background thread so annotation saves return immediately.
    """
    if not text or not text.strip():
        return
    try:
        # FTS — always, no API key needed
        conn = get_db_connection()
        try:
            conn.execute('DELETE FROM annotations_fts WHERE annotation_id=?', (ann_id,))
            conn.execute(
                'INSERT INTO annotations_fts (user_note, annotation_id) VALUES (?,?)',
                (text, ann_id)
            )
            conn.commit()
        except Exception as e:
            log.warning(f'annotations_fts insert failed: {e}')

        # Semantic embedding — only if Gemini key available and vec works
        if gemini_key and VEC_AVAILABLE:
            vec = embed_query(text, gemini_key)  # embed_query works for short texts too
            if vec:
                try:
                    conn.execute('DELETE FROM vec_annotations WHERE annotation_id=?', (ann_id,))
                    conn.execute(
                        'INSERT INTO vec_annotations (annotation_id, embedding) VALUES (?,?)',
                        (ann_id, vec)
                    )
                    conn.commit()
                except Exception as e:
                    log.warning(f'vec_annotations insert failed: {e}')
        conn.close()
    except Exception as e:
        log.error(f'embed_annotation_background failed for {ann_id}: {e}')

def ingest_paper_background(paper_id: str, bibcode: str, identifiers: list,
                             ads_token: str = '', gemini_key: str = ''):
    try:
        conn  = get_db_connection()
        paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
        conn.close()
        if not paper:
            return
        paper_dict = dict(paper)
        paper_dict['identifiers'] = identifiers or []

        content, source_type, source_url, no_free_pdf = fetch_content_for_paper(
            paper_dict, ads_token
        )
        if not content:
            conn = get_db_connection()
            # pdf_extracted=3 → no free PDF (paywalled) — use grey dot
            # pdf_extracted=2 → fetch/extraction error — use red dot, can retry
            extracted_val = 3 if no_free_pdf else 2
            conn.execute('UPDATE papers SET pdf_extracted=? WHERE id=?',
                         (extracted_val, paper_id))
            conn.commit()
            conn.close()
            return

        # ── Auto-save PDF to Drive if we got PDF bytes and don't already
        #    have a Drive file_id for this paper ──────────────────────────
        if source_type == 'pdf' and not (paper_dict.get('file_id') or '').strip():
            safe_name = (paper_dict.get('bibkey') or bibcode or paper_id) + '.pdf'
            # Look up library name for subfolder routing — use separate conn
            lib_name = ''
            try:
                conn_meta = get_db_connection()
                lib_row   = conn_meta.execute(
                    'SELECT name FROM libraries WHERE id = '
                    '(SELECT library_id FROM papers WHERE id=?)', (paper_id,)
                ).fetchone()
                lib_name = lib_row['name'] if lib_row else ''
                conn_meta.close()
            except Exception as e:
                log.warning(f'Could not look up library name for {paper_id}: {e}')
            # Upload to Drive in background so text extraction isn't delayed
            def _do_upload(pdf_bytes, fname, lname, pid, bc):
                drive_file_id = upload_pdf_via_gas(pdf_bytes, fname, lname)
                if drive_file_id:
                    try:
                        conn_up = get_db_connection()
                        conn_up.execute(
                            'UPDATE papers SET file_id=?, content_source_url=? WHERE id=?',
                            (drive_file_id, f'drive:{drive_file_id}', pid)
                        )
                        conn_up.commit()
                        conn_up.close()
                        log.info(f'Auto-saved PDF to Drive via GAS for {bc}: {drive_file_id} (library={lname})')
                    except Exception as e:
                        log.warning(f'Could not update file_id after upload: {e}')
            threading.Thread(
                target=_do_upload,
                args=(content, safe_name, lib_name, paper_id, bibcode),
                daemon=True
            ).start()

        if source_type == 'pdf':
            text = extract_text_from_pdf(content)
        else:
            text = extract_text_from_html(content)
            if isinstance(text, str):
                text = [(1, [(text, 0.0, 0.0, 1.0, 1.0)])]

        if not text:
            conn = get_db_connection()
            conn.execute('UPDATE papers SET pdf_extracted=2 WHERE id=?', (paper_id,))
            conn.commit()
            conn.close()
            return

        passages = chunk_text(text, paper_id)
        if passages:
            write_passages_to_db(paper_id, passages, bibcode, source_url)
            log.info(f'Ingest complete: {bibcode} — {len(passages)} passages')
    except Exception as e:
        log.error(f'ingest_paper_background failed for {paper_id}: {e}')

# ── Helpers ───────────────────────────────────────────────────────────────────
def rows_to_list(rows) -> list:
    return [dict(r) for r in rows]
# ── Drive service (for PDF fetch only) ───────────────────────────────────────
def get_drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    sa_path = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON', '')
    if sa_path and Path(sa_path).exists():
        creds = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        return build('drive', 'v3', credentials=creds)
    raise RuntimeError('GOOGLE_SERVICE_ACCOUNT_JSON not configured')

def upload_pdf_via_gas(pdf_bytes: bytes, filename: str,
                        library_name: str = '') -> str | None:
    """
    Upload PDF bytes to Drive via GAS webapp (runs as deployer = real Google
    account with full storage quota). Bypasses service account quota limit.
    Saves into BibMan_PDFs/<library_name>/ subfolder (auto-created if needed).
    Requires GAS_WEBAPP_URL environment variable set in bibman.service.
    Returns Drive file_id on success, None on failure.
    """
    gas_url    = CONFIG.get('gas_webapp_url', '').strip() or os.environ.get('GAS_WEBAPP_URL', '').strip()
    credential = GAS_CREDENTIAL
    if not gas_url:
        log.warning('upload_pdf_via_gas: GAS_WEBAPP_URL not set in environment')
        return None
    try:
        pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
        payload = {
            'action':       'upload_pdf',
            'credential':   credential,
            'filename':     filename,
            'library_name': library_name,
            'pdf_base64':   pdf_b64,
        }
        # GAS POST flow:
        # 1. POST to script.google.com → 302 redirect to script.googleusercontent.com/macros/echo
        # 2. The echo URL must be fetched as GET (it returns the doPost response body)
        # So: POST with allow_redirects=True (default) lets requests follow as GET automatically
        # which is exactly what we want for the echo endpoint.
        r = requests.post(
            gas_url,
            json=payload,
            timeout=120,
            headers={'Content-Type': 'application/json'},
            allow_redirects=True,  # follows 302 as GET to echo endpoint — correct
        )
        r.raise_for_status()
        result = r.json()
        if result.get('ok') and result.get('file_id'):
            log.info(f'upload_pdf_via_gas: saved {filename} → {result["file_id"]}')
            return result['file_id']
        else:
            log.warning(f'upload_pdf_via_gas failed for {filename}: {result.get("error","unknown")}')
            return None
    except Exception as e:
        log.warning(f'upload_pdf_via_gas exception for {filename}: {e}')
        return None

# ═════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═════════════════════════════════════════════════════════════════════════════



_CRON_RUNNING = False  # simple lock to prevent simultaneous cron runs

@app.route('/api/cron/run', methods=['POST'])
@gas_auth_required
def run_cron():
    global _CRON_RUNNING
    if _CRON_RUNNING:
        return jsonify({'ok': False, 'error': 'Cron job already running'}), 409

    _, gemini_key = get_request_tokens()
    if not gemini_key:
        return jsonify({'ok': False, 'error': 'No Gemini key provided'}), 400

    def _cron_job(gemini_key: str, embed_model: str, generate_model: str):
        global _CRON_RUNNING
        _CRON_RUNNING = True
        log.info('=== GAS-triggered cron job starting ===')
        start = time.time()
        try:
            # ── Step 1: Embeddings ────────────────────────────────────────────
            log.info('--- Cron Step 1: Generating embeddings ---')
            embedded = 0
            try:
                conn = get_db_connection()
                rows = conn.execute('''
                    SELECT pa.id, pa.text, pp.bibcode
                    FROM passages pa
                    JOIN papers pp ON pp.id = pa.paper_id
                    WHERE pa.text IS NOT NULL
                      AND pa.id NOT IN (SELECT id FROM vec_passages_rowids)
                    ORDER BY pp.bibcode, pa.passage_index
                    LIMIT 5000
                ''').fetchall()
                conn.close()
                if not rows:
                    log.info('Cron: no passages need embedding')
                else:
                    log.info(f'Cron: found {len(rows)} passages needing embeddings')
                    passages = [{'id': r['id'], 'text': r['text']} for r in rows]
                    vectors  = embed_passages(passages, gemini_key, embed_model)
                    if vectors:
                        conn = get_db_connection()
                        for pid, vec_bytes in vectors:
                            try:
                                conn.execute(
                                    'INSERT OR IGNORE INTO vec_passages (passage_id, embedding) VALUES (?,?)',
                                    (pid, vec_bytes)
                                )
                            except Exception as e:
                                log.warning(f'Cron vec_passages insert failed for {pid}: {e}')
                        conn.commit()
                        conn.close()
                        embedded = len(vectors)
                        log.info(f'Cron: embedded {embedded} passages')
            except Exception as e:
                log.error(f'Cron embedding step failed: {e}')

            # ── Step 2: Synonyms ──────────────────────────────────────────────
            log.info('--- Cron Step 2: Generating synonyms ---')
            synonyms = 0
            try:
                conn = get_db_connection()
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
                    log.info('Cron: no papers need synonym generation')
                else:
                    log.info(f'Cron: found {len(rows)} papers needing synonyms')
                    for row in rows:
                        try:
                            conn = get_db_connection()
                            n = suggest_synonyms_for_paper(
                                row['id'], row['library_id'], conn, gemini_key, generate_model
                            )
                            conn.close()
                            if n:
                                log.info(f'Cron: {row["bibcode"]}: suggested {n} synonym pairs')
                            synonyms += 1
                        except Exception as e:
                            log.warning(f'Cron synonym failed for {row["bibcode"]}: {e}')
                            try: conn.close()
                            except Exception: pass
                        time.sleep(1)
                    log.info(f'Cron: synonym generation complete: {synonyms} papers processed')
            except Exception as e:
                log.error(f'Cron synonym step failed: {e}')

            elapsed = time.time() - start
            log.info(f'=== GAS-triggered cron complete in {elapsed:.0f}s: {embedded} embeddings, {synonyms} synonym papers ===')

        finally:
            _CRON_RUNNING = False

    embed_model, generate_model = get_request_models()
    threading.Thread(target=_cron_job, args=(gemini_key, embed_model, generate_model), daemon=True).start()
    return jsonify({'ok': True, 'started': True, 'message': 'Cron job started in background'})



@app.route('/health')
def health():
    return jsonify({
        'status':      'healthy',
        'db_exists':   DB_PATH.exists(),
        'db_size_mb':  round(DB_PATH.stat().st_size / 1024 / 1024, 1) if DB_PATH.exists() else 0,
        'vec_enabled': VEC_AVAILABLE,
    })

# ── Library stats (lightweight, for cache invalidation) ──────────────────────
@app.route('/api/libraries/<library_name>/stats')
@export_auth_required
def library_stats(library_name):
    conn = get_db_connection()
    lib = conn.execute(
        'SELECT id FROM libraries WHERE name=?', (library_name,)
    ).fetchone()
    if not lib:
        conn.close()
        return err('Library not found', 404)
    row = conn.execute(
        'SELECT COUNT(*) as n, MAX(rowid) as last_rowid FROM papers WHERE library_id=?',
        (lib['id'],)
    ).fetchone()
    conn.close()
    return jsonify({
        'library':    library_name,
        'count':      row['n'],
        'last_rowid': row['last_rowid']
    })

@app.route('/api/libraries/full', methods=['GET'])
@gas_auth_required
def get_libraries_full():
    conn = get_db_connection()
    try:
        libs = conn.execute(
            'SELECT id, name FROM libraries ORDER BY name'
        ).fetchall()
        library_id, library_name = get_current_library_id(conn)
        return jsonify({
            'libraries': [{'id': r['id'], 'name': r['name']} for r in libs],
            'current': library_name or ''
        })
    finally:
        conn.close()

# ── GooTeX loopback: get bib file ─────────────────────────────────────────────
@app.route('/get_bib')
def get_bib():
    """
    Internal loopback for GooTeX. Returns raw BibTeX for a library.
    Called as: GET http://localhost:8081/get_bib?library=Extragalactic
    No authentication — localhost only (nginx must not expose this externally).
    """
    library_name_req = request.args.get('library', '').strip()
    conn = get_db_connection()

    if library_name_req:
        lib = conn.execute(
            'SELECT id, name FROM libraries WHERE name=?', (library_name_req,)
        ).fetchone()
    else:
        lib = None

    if not lib:
        library_id, library_name = get_current_library_id(conn)
    else:
        library_id   = lib['id']
        library_name = lib['name']

    if not library_id:
        conn.close()
        return Response('% No library found\n', mimetype='text/plain')

    rows = conn.execute('''
        SELECT bibkey, bibtex, title, authors, year, journal,
               volume, pages, pubtype, doi, bibcode
        FROM papers WHERE library_id=? ORDER BY bibkey
    ''', (library_id,)).fetchall()
    conn.close()

    lines = [
        f'% BibMan export — {library_name}',
        f'% Generated: {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}',
        f'% {len(rows)} entries', '',
    ]
    for row in rows:
        bibkey  = row['bibkey'] or 'unknown'
        pubtype = row['pubtype'] or 'article'
        if row['bibtex'] and row['bibtex'].strip():
            fixed = re.sub(r'@\w+\{[^,]+,',
                           f'@{pubtype}{{{bibkey},',
                           row['bibtex'].strip(), count=1, flags=re.IGNORECASE)
            lines.append(fixed)
        else:
            entry = [f'@{pubtype}{{{bibkey},']
            entry.append(f'  author  = {{{row["authors"] or "Unknown"}}},')
            entry.append(f'  title   = {{{row["title"] or "Unknown"}}},')
            if row['year']:    entry.append(f'  year    = {{{row["year"]}}},')
            if row['journal']: entry.append(f'  journal = {{{row["journal"]}}},')
            if row['volume']:  entry.append(f'  volume  = {{{row["volume"]}}},')
            if row['pages']:   entry.append(f'  pages   = {{{row["pages"]}}},')
            if row['doi']:     entry.append(f'  doi     = {{{row["doi"]}}},')
            if row['bibcode']: entry.append(
                f'  adsurl  = {{https://ui.adsabs.harvard.edu/abs/{row["bibcode"]}}},')
            entry.append('}')
            lines.append('\n'.join(entry))
        lines.append('')

    return Response('\n'.join(lines), mimetype='text/plain; charset=utf-8')

# ── Export bib (GAS-authenticated) ───────────────────────────────────────────
@app.route('/api/export/bib-text')
@export_auth_required
def export_bib_text():
    """Same as /get_bib but requires GAS credential. For external access."""
    return get_bib()

# ── Shared bibkey construction helper ────────────────────────────────────────
import unicodedata as _ucd

def _make_bibkey(authors, year, journal, volume, pages, pubtype='article', booktitle=''):
    """Construct a BibMan-format bibkey: firstauthor[+]yearjshortvolume_page"""
    # Normalize first author name — strip accents, keep only a-z
    first_raw = (authors.split(';')[0].split(',')[0]).strip()
    first_raw = _ucd.normalize('NFKD', first_raw)
    first_raw = ''.join(c for c in first_raw if not _ucd.combining(c))
    first = re.sub(r'[^a-z]', '', first_raw.lower())
    if not first:
        first = 'ref'
    has_multiple = ';' in (authors or '')
    plus = '+' if has_multiple else ''
    yr = str(year or '')
    # Use booktitle as fallback when no journal (for inbook, incollection, inproceedings)
    title_src = (journal or '').strip() or (booktitle or '').strip()
    # Journal/booktitle short form — strip leading backslash from LaTeX macros
    j = title_src
    j = re.sub(r'^\\', '', j)   # strip leading backslash
    j = re.sub(r'[^a-z0-9]', '', j.lower())
    # For booktitle, take first meaningful word only (max 10 chars) to keep bibkey short
    if not (journal or '').strip() and (booktitle or '').strip():
        words = re.sub(r'[^a-z0-9 ]', '', booktitle.lower()).split()
        stopwords = {'of','the','and','in','for','a','an','on','to','at','by'}
        words = [w for w in words if w not in stopwords]
        j = words[0][:10] if words else 'book'
    vol = re.sub(r'[^a-z0-9]', '', str(volume or '').lower())
    pg  = re.sub(r'[^a-z0-9]', '', str(pages  or '').split('-')[0].split('–')[0].lower())
    bibkey = first + plus + yr
    if j and vol and pg:
        bibkey += j + vol + '_' + pg
    elif j and vol:
        bibkey += j + vol
    elif j:
        bibkey += j
    else:
        # No journal — use pubtype suffix
        suffix_map = {
            'article':       '',
            'inproceedings': 'inproceedings',
            'proceedings':   'inproceedings',
            'book':          'book',
            'booklet':       'book',
            'inbook':        'book',
            'incollection':  'book',
            'bookchapter':   'book',
            'phdthesis':     'phd',
            'mastersthesis': 'msc',
            'techreport':    'tech',
            'manual':        'misc',
            'unpublished':   'misc',
            'misc':          'misc',
            'erratum':       'misc',
            'eprint':        'misc',
            'abstract':      'misc',
            'software':      'software',
            'dataset':       'data',
            'webpage':       'misc',
        }
        sfx = suffix_map.get((pubtype or 'misc').lower(), 'misc')
        if sfx:
            bibkey += '_' + sfx
    return re.sub(r'[^a-z0-9+_]', '', bibkey)

# ── Direct bookmarklet endpoint ───────────────────────────────────────────────
@app.route('/api/papers/add-direct', methods=['POST'])
@gas_auth_required
def add_paper_direct():
    """
    Direct write from bookmarklet (via GAS proxy).
    GAS frontend resolves identifiers via ADS and sends clean paper data here.
    Body must contain: title, authors, year, and optionally all other fields.
    """
    data     = request.json or {}
    title    = (data.get('title')   or '').strip()
    authors  = (data.get('authors') or '').strip()
    year     = str(data.get('year') or '').strip()
    if not title or not authors or not year:
        return err('title, authors, and year required')

    _, gemini_key = get_request_tokens()
    user_id  = get_user_id()
    conn     = get_db_connection()
    # Prefer explicit library from client; fall back to server CONFIG
    explicit_lib = (data.get('library') or '').strip()
    if explicit_lib:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (explicit_lib,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
    else:
        library_id, _ = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)

    bibcode  = (data.get('bibcode')  or '').strip()
    doi      = (data.get('doi')      or '').strip()
    journal  = (data.get('journal')  or '').strip()
    volume   = (data.get('volume')   or '').strip()
    pages    = (data.get('pages')    or '').strip()
    pdf_url  = (data.get('pdf_url')  or '').strip()
    pubtype  = (data.get('pubtype')  or 'article').strip()
    abstract = (data.get('abstract') or '').strip()
    bibtex   = (data.get('bibtex')   or '').strip()
    tags     = (data.get('tags')     or '').strip()
    identifiers = data.get('identifiers', [])

    # Duplicate check by bibcode or bibkey
    bibkey = (data.get('bibkey') or '').strip()
    # Sanitize bibkey — strip accents then everything except a-z, 0-9, + and _
    def _norm_bibkey(s):
        s = _ucd.normalize('NFKD', s)
        s = ''.join(c for c in s if not _ucd.combining(c))
        return re.sub(r'[^a-z0-9+_]', '', s.lower())
    bibkey = _norm_bibkey(bibkey)
    if not bibkey:
        # Server-side fallback: construct bibkey in standard format
        first_author = re.sub(r'[^a-z]', '',
            _ucd.normalize('NFKD', (authors.split(';')[0].split(',')[0]).strip().lower())
            .encode('ascii', 'ignore').decode())
        has_multiple = ';' in (authors or '') or ' and ' in (authors or '')
        j = re.sub(r'^\\', '', (journal or '').strip()).lower().replace(' ','')
        vol   = (volume or '').strip()
        pg    = (pages  or '').strip().split('-')[0].split('\u2013')[0]
        bibkey = first_author
        if has_multiple: bibkey += '+'
        bibkey += (year or '')
        if j:   bibkey += j
        if vol: bibkey += vol
        if pg:  bibkey += '_' + pg
        bibkey = re.sub(r'[^a-z0-9+_]', '', bibkey)

    if bibcode:
        existing = conn.execute(
            'SELECT id, bibkey FROM papers WHERE library_id=? AND bibcode=?',
            (library_id, bibcode)
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({'ok': True, 'duplicate': True, 'bibkey': existing['bibkey'],
                            'message': f'Already in library as {existing["bibkey"]}'})
    if doi:
        existing = conn.execute(
            'SELECT id, bibkey FROM papers WHERE library_id=? AND doi=?',
            (library_id, doi)
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({'ok': True, 'duplicate': True, 'bibkey': existing['bibkey'],
                            'message': f'Already in library as {existing["bibkey"]}'})
    if title:
        norm_title = re.sub(r'\W+', '', title.lower())
        title_rows = conn.execute(
            'SELECT id, bibkey, title FROM papers WHERE library_id=?',
            (library_id,)
        ).fetchall()
        for row in title_rows:
            if re.sub(r'\W+', '', (row['title'] or '').lower()) == norm_title:
                conn.close()
                return jsonify({'ok': True, 'duplicate': True, 'bibkey': row['bibkey'],
                                'message': f'Already in library as {row["bibkey"]}'})

    # Ensure unique bibkey
    base_key = bibkey
    suffix   = 0
    while conn.execute(
        'SELECT id FROM papers WHERE library_id=? AND bibkey=?', (library_id, bibkey)
    ).fetchone():
        suffix += 1
        if suffix > 25:
            bibkey = f'{base_key}_{uuid.uuid4().hex[:4]}'
            break
        bibkey = f'{base_key}{chr(96+suffix)}'

    paper_id = str(uuid.uuid4())
    conn.execute('''
        INSERT INTO papers
            (id,library_id,bibkey,title,authors,year,journal,
             volume,pages,pubtype,bibcode,doi,pdf_url,bibtex,
             abstract,tags,added_by,read_status,pdf_extracted)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (paper_id, library_id, bibkey, title, authors, year, journal,
            volume, pages, pubtype, bibcode, doi, pdf_url, bibtex,
            abstract, tags, user_id, 'unread', 0))
    conn.commit()
    conn.close()

    threading.Thread(
        target=ingest_paper_background,
        args=(paper_id, bibcode, identifiers, '', gemini_key),
        daemon=True
    ).start()

    return jsonify({'ok': True, 'duplicate': False, 'bibkey': bibkey,
                    'message': f'Added {bibkey}'})


# ── Library ───────────────────────────────────────────────────────────────────
@app.route('/api/library')
@gas_auth_required
def get_library():
    conn = get_db_connection()
    library_id, library_name = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)
    count = conn.execute(
        'SELECT COUNT(*) FROM papers WHERE library_id=?', (library_id,)
    ).fetchone()[0]
    conn.close()
    return jsonify({'library_id': library_id, 'library_name': library_name,
                    'paper_count': count})

@app.route('/api/libraries')
@gas_auth_required
def list_libraries():
    conn  = get_db_connection()
    rows  = conn.execute('SELECT id, name FROM libraries ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/libraries/current')
@gas_auth_required
def get_current_library():
    library_id, library_name = get_current_library_id()
    return jsonify({'library_id': library_id, 'library_name': library_name})

@app.route('/api/libraries/switch', methods=['POST'])
@gas_auth_required
def switch_library():
    data     = request.json or {}
    lib_name = (data.get('library_name') or '').strip()
    if not lib_name:
        return err('library_name required')
    conn = get_db_connection()
    lib  = conn.execute(
        'SELECT id, name FROM libraries WHERE name=?', (lib_name,)
    ).fetchone()
    conn.close()
    if not lib:
        return err(f'Library not found: {lib_name}', 404)
    CONFIG['library_name'] = lib['name']
    save_config(CONFIG)
    return jsonify({'ok': True, 'library_name': lib['name']})

@app.route('/api/libraries', methods=['POST'])
@gas_auth_required
def create_library():
    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return err('name required')
    lib_id = str(uuid.uuid4())
    conn   = get_db_connection()
    try:
        conn.execute('INSERT INTO libraries (id, name) VALUES (?,?)', (lib_id, name))
        conn.commit()
    except Exception as e:
        conn.close()
        return err(str(e))
    conn.close()
    return jsonify({'ok': True, 'library_id': lib_id, 'name': name})

@app.route('/api/libraries/<library_id>', methods=['DELETE'])
@gas_auth_required
def delete_library(library_id):
    """
    Delete a library and all its papers, passages, annotations, and embeddings.
    Refuses to delete if it is the last remaining library.
    """
    conn = get_db_connection()
    # Safety check — don't delete the last library
    count = conn.execute('SELECT COUNT(*) FROM libraries').fetchone()[0]
    if count <= 1:
        conn.close()
        return err('Cannot delete the last remaining library')
    
    lib = conn.execute('SELECT name FROM libraries WHERE id=?', 
                      (library_id,)).fetchone()
    if not lib:
        conn.close()
        return err('Library not found', 404)
    lib_name = lib['name']

    # Get all paper IDs in this library
    paper_ids = [r['id'] for r in conn.execute(
        'SELECT id FROM papers WHERE library_id=?', (library_id,)
    ).fetchall()]

    # Delete embeddings, passages, annotations for all papers
    for paper_id in paper_ids:
        old_ids = [r['id'] for r in conn.execute(
            'SELECT id FROM passages WHERE paper_id=?', (paper_id,)
        ).fetchall()]
        if old_ids:
            ph = ','.join('?'*len(old_ids))
            try:
                conn.execute(
                    f'DELETE FROM vec_passages WHERE passage_id IN ({ph})', old_ids
                )
            except Exception:
                pass
            conn.execute('DELETE FROM passages WHERE paper_id=?', (paper_id,))
        conn.execute('DELETE FROM annotations WHERE paper_id=?', (paper_id,))

    # Delete all papers and the library itself
    conn.execute('DELETE FROM papers WHERE library_id=?', (library_id,))
    conn.execute('DELETE FROM libraries WHERE id=?', (library_id,))
    conn.commit()
    conn.close()

    log.info(f'Deleted library: {lib_name} ({len(paper_ids)} papers removed)')
    return jsonify({'ok': True, 'deleted': lib_name, 'papers_removed': len(paper_ids)})

# ── Papers ────────────────────────────────────────────────────────────────────
@app.route('/api/papers')
@gas_auth_required
def list_papers():
    conn = get_db_connection()
    # Allow client to explicitly specify library to avoid server-side state mismatch
    library_param = request.args.get('library', '').strip()
    if library_param:
        lib = conn.execute('SELECT id FROM libraries WHERE name=?', (library_param,)).fetchone()
        library_id = lib['id'] if lib else None
    else:
        library_id, _ = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return jsonify([])
    user_id = get_user_id()
    show_all = request.args.get('everyone', '0') == '1'

    if show_all:
        rows = conn.execute('''
            SELECT p.id, p.bibkey, p.title, p.authors, p.year, p.journal,
                   p.volume, p.pages, p.pubtype, p.bibcode, p.doi,
                   p.read_status, p.pdf_extracted, p.pdf_url, p.file_id,
                   p.key_paper, p.pinned, p.followup,
                   CASE WHEN p.synonyms_generated_at IS NOT NULL THEN 1 ELSE 0 END AS embeddings_done,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id) AS has_annotations,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id
                    AND a.user_note IS NOT NULL AND a.user_note != '') AS note_count,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id
                    AND (a.quote IS NOT NULL AND a.quote != '')
                    AND (a.user_note IS NULL OR a.user_note = '')) AS highlight_count
            FROM papers p WHERE p.library_id=? ORDER BY p.bibkey COLLATE NOCASE
        ''', (library_id,)).fetchall()
    else:
        rows = conn.execute('''
            SELECT p.id, p.bibkey, p.title, p.authors, p.year, p.journal,
                   p.volume, p.pages, p.pubtype, p.bibcode, p.doi,
                   p.read_status, p.pdf_extracted, p.pdf_url, p.file_id,
                   p.key_paper, p.pinned, p.followup,
                   CASE WHEN p.synonyms_generated_at IS NOT NULL THEN 1 ELSE 0 END AS embeddings_done,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id
                    AND a.username = ?) AS has_annotations,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id
                    AND a.username = ?
                    AND a.user_note IS NOT NULL AND a.user_note != '') AS note_count,
                   (SELECT COUNT(*) FROM annotations a
                    WHERE a.paper_id = p.id
                    AND a.username = ?
                    AND (a.quote IS NOT NULL AND a.quote != '')
                    AND (a.user_note IS NULL OR a.user_note = '')) AS highlight_count
            FROM papers p WHERE p.library_id=? ORDER BY p.bibkey COLLATE NOCASE
        ''', (user_id, user_id, user_id, library_id)).fetchall()

    papers = rows_to_list(rows)

    # Fetch tags for all papers in one query
    # Fetch all tags (paper-level and annotation-level), deduplicated by paper+user+label
    if show_all:
        tag_rows = conn.execute('''
            SELECT DISTINCT pt.paper_id, pt.user_id, l.id as label_id, l.label, l.color
            FROM paper_tags pt
            JOIN user_tag_labels l ON l.id = pt.label_id
            JOIN papers p ON p.id = pt.paper_id
            WHERE p.library_id = ?
            ORDER BY pt.user_id, l.label
        ''', (library_id,)).fetchall()
    else:
        tag_rows = conn.execute('''
            SELECT DISTINCT pt.paper_id, pt.user_id, l.id as label_id, l.label, l.color
            FROM paper_tags pt
            JOIN user_tag_labels l ON l.id = pt.label_id
            JOIN papers p ON p.id = pt.paper_id
            WHERE p.library_id = ? AND pt.user_id = ?
            ORDER BY l.label
        ''', (library_id, user_id)).fetchall()
    conn.close()

    # Group tags by paper_id
    tags_by_paper = {}
    for t in tag_rows:
        pid = t['paper_id']
        if pid not in tags_by_paper:
            tags_by_paper[pid] = []
        tags_by_paper[pid].append({
            'label_id': t['label_id'],
            'label':    t['label'],
            'color':    t['color'],
            'user_id':  t['user_id'],
        })
    for p in papers:
        p['tags_data'] = tags_by_paper.get(p['id'], [])
    return jsonify(papers)

@app.route('/api/papers/<paper_id>')
@gas_auth_required
def get_paper(paper_id):
    conn  = get_db_connection()
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    if not paper:
        conn.close()
        return err('Paper not found', 404)
    result = dict(paper)
    # If no stored bibtex, generate one from fields so View BibTeX always has content
    if not result.get('bibtex'):
        bibkey  = result.get('bibkey') or 'unknown'
        pubtype = result.get('pubtype') or 'article'
        entry   = [f'@{pubtype}{{{bibkey},']
        if result.get('authors'): entry.append(f'  author  = {{{result["authors"]}}},')
        if result.get('title'):   entry.append(f'  title   = {{{result["title"]}}},')
        if result.get('year'):    entry.append(f'  year    = {{{result["year"]}}},')
        if result.get('journal'): entry.append(f'  journal = {{{result["journal"]}}},')
        if result.get('volume'):  entry.append(f'  volume  = {{{result["volume"]}}},')
        if result.get('pages'):   entry.append(f'  pages   = {{{result["pages"]}}},')
        if result.get('doi'):     entry.append(f'  doi     = {{{result["doi"]}}},')
        if result.get('bibcode'): entry.append(
            f'  adsurl  = {{https://ui.adsabs.harvard.edu/abs/{result["bibcode"]}}},')
        entry.append('}')
        result['bibtex'] = '\n'.join(entry)
    # Include annotations so Paper View can display them
    everyone = request.args.get('everyone', '0') == '1'
    user_id  = get_user_id()
    if everyone:
        anns = conn.execute(
            'SELECT * FROM annotations WHERE paper_id=? ORDER BY created_at',
            (paper_id,)
        ).fetchall()
    else:
        anns = conn.execute(
            'SELECT * FROM annotations WHERE paper_id=? AND username=? ORDER BY created_at',
            (paper_id, user_id)
        ).fetchall()
    ann_list = []
    for a in anns:
        d = dict(a)
        # Normalise text fields: old schema uses user_note, new uses text
        d['display_text'] = d.get('user_note') or d.get('text') or ''
        d['quote']        = d.get('quote') or ''
        # Parse coords JSON — two possible formats:
        # Old (BibMan 1.0): [{x0, y0, x1, y1, page}, ...]  where x0=left, x1=right
        # New (current):    [{x1, y1, x2, y2, page}, ...]  where x1=left, x2=right
        coords_raw = d.get('coords')
        rects = []
        if coords_raw and isinstance(coords_raw, str):
            try:
                c = json.loads(coords_raw)
                items = c if isinstance(c, list) else [c]
                for r in items:
                    if not isinstance(r, dict):
                        continue
                    # Detect format by presence of x0 (old) vs x2 (new)
                    if 'x0' in r:
                        # Old format: x0=left, y0=top, x1=right, y1=bottom
                        rects.append({
                            'x1':   r.get('x0', 0),
                            'y1':   r.get('y0', 0),
                            'x2':   r.get('x1', 1),
                            'y2':   r.get('y1', 1),
                            'page': r.get('page', 1),
                        })
                    else:
                        # New format: x1=left, y1=top, x2=right, y2=bottom
                        rects.append({
                            'x1':   r.get('x1', 0),
                            'y1':   r.get('y1', 0),
                            'x2':   r.get('x2', 1),
                            'y2':   r.get('y2', 1),
                            'page': r.get('page', 1),
                        })
            except Exception:
                pass
        d['rects'] = rects
        # Also set top-level page_number from first rect for backwards compat
        if rects:
            d['page_number'] = rects[0]['page']
            d['x1'] = rects[0]['x1']
            d['y1'] = rects[0]['y1']
            d['x2'] = rects[0]['x2']
            d['y2'] = rects[0]['y2']
        ann_list.append(d)
    result['annotations'] = ann_list
    conn.close()
    return jsonify(result)

@app.route('/api/papers/<paper_id>', methods=['PATCH'])
@gas_auth_required
def update_paper(paper_id):
    data    = request.json or {}
    allowed = {'title','authors','year','journal','volume','pages',
               'pubtype','bibcode','doi','pdf_url','file_id','bibtex','bibkey',
               'key_paper','pinned','followup'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return err('No valid fields')
    sets   = ', '.join(f'{k}=?' for k in updates)
    values = list(updates.values()) + [paper_id]
    conn   = get_db_connection()
    conn.execute(f'UPDATE papers SET {sets} WHERE id=?', values)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/papers/<paper_id>', methods=['DELETE'])
@gas_auth_required
def delete_paper(paper_id):
    conn = get_db_connection()
    # Delete passages + embeddings first
    old_ids = [r['id'] for r in conn.execute(
        'SELECT id FROM passages WHERE paper_id=?', (paper_id,)
    ).fetchall()]
    if old_ids:
        ph = ','.join('?'*len(old_ids))
        try:
            conn.execute(f'DELETE FROM vec_passages WHERE passage_id IN ({ph})', old_ids)
        except Exception:
            pass
        conn.execute('DELETE FROM passages WHERE paper_id=?', (paper_id,))
    conn.execute('DELETE FROM annotations WHERE paper_id=?', (paper_id,))
    conn.execute('DELETE FROM papers WHERE id=?', (paper_id,))
    conn.commit()
    conn.close()
    # Note: Drive PDF intentionally not deleted here — service account
    # Drive deletion was blocking gunicorn sync worker (60-75s delays).
    return jsonify({'ok': True})

@app.route('/api/papers/<paper_id>/read-status', methods=['PATCH'])
@gas_auth_required
def update_read_status(paper_id):
    data   = request.json or {}
    status = data.get('read_status', 'unread')
    conn   = get_db_connection()
    conn.execute('UPDATE papers SET read_status=? WHERE id=?', (status, paper_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/papers/<paper_id>/bibtex', methods=['PUT'])
@gas_auth_required
def update_paper_bibtex(paper_id):
    data  = request.json or {}
    bib   = (data.get('bibtex') or '').strip()
    conn  = get_db_connection()
    # Extract bibkey from BibTeX string e.g. @article{smith2020apj,...
    bibkey_match = re.search(r'@\w+\{([^,]+),', bib)
    if bibkey_match:
        new_bibkey = bibkey_match.group(1).strip()
        conn.execute('UPDATE papers SET bibtex=?, bibkey=? WHERE id=?',
                     (bib, new_bibkey, paper_id))
    else:
        conn.execute('UPDATE papers SET bibtex=? WHERE id=?', (bib, paper_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/papers/<paper_id>/pdf-source', methods=['PATCH'])
@gas_auth_required
def set_pdf_source(paper_id):
    data    = request.json or {}
    pdf_url = (data.get('pdf_url') or '').strip()
    file_id = (data.get('file_id') or '').strip()
    conn    = get_db_connection()
    if pdf_url:
        conn.execute('UPDATE papers SET pdf_url=?, pdf_extracted=0 WHERE id=?',
                     (pdf_url, paper_id))
    if file_id:
        conn.execute('UPDATE papers SET file_id=?, pdf_extracted=0 WHERE id=?',
                     (file_id, paper_id))
    conn.commit()
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    conn.close()
    ads_token, gemini_key = get_request_tokens()
    if paper:
        threading.Thread(
            target=ingest_paper_background,
            args=(paper_id, paper['bibcode'] or '', [],
                  ads_token, gemini_key),
            daemon=True
        ).start()
    return jsonify({'ok': True})

@app.route('/api/papers/<paper_id>/ingest-status')
@gas_auth_required
def get_ingest_status(paper_id):
    conn  = get_db_connection()
    paper = conn.execute(
        'SELECT pdf_extracted, pdf_url, file_id, bibcode FROM papers WHERE id=?',
        (paper_id,)
    ).fetchone()
    count = conn.execute(
        'SELECT COUNT(*) FROM passages WHERE paper_id=?', (paper_id,)
    ).fetchone()[0]
    # Count passages that have embeddings — use subquery to avoid JOIN on virtual table
    try:
        passage_ids = [r[0] for r in conn.execute(
            'SELECT id FROM passages WHERE paper_id=?', (paper_id,)
        ).fetchall()]
        if passage_ids:
            ph = ','.join('?' * len(passage_ids))
            emb_count = conn.execute(
                f'SELECT COUNT(*) FROM vec_passages WHERE passage_id IN ({ph})',
                passage_ids
            ).fetchone()[0]
        else:
            emb_count = 0
    except Exception as e:
        log.warning(f'embedded_count query failed: {e}')
        emb_count = None
    conn.close()
    if not paper:
        return err('Paper not found', 404)
    return jsonify({
        'pdf_extracted': paper['pdf_extracted'],
        'passage_count': count,
        'embedded_count': emb_count,
        'has_pdf_url':   bool(paper['pdf_url']),
        'has_file_id':   bool(paper['file_id']),
        'bibcode':       paper['bibcode'],
    })

@app.route('/api/papers/<paper_id>/rerun-ingest', methods=['POST'])
@gas_auth_required
def rerun_ingest(paper_id):
    conn  = get_db_connection()
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    conn.close()
    if not paper:
        return err('Paper not found', 404)

    ads_token, gemini_key = get_request_tokens()

    def _run():
        paper_dict = dict(paper)
        paper_dict['identifiers'] = []
        bibcode    = paper_dict.get('bibcode', '')
        log.info(f'rerun_ingest background start: paper_id={paper_id} bibcode={bibcode!r}')

        content, source_type, source_url, no_free_pdf = fetch_content_for_paper(paper_dict, ads_token)
        if not content:
            log.warning(f'rerun_ingest: no content source for {paper_id}')
            return

        log.info(f'rerun_ingest: fetched {source_type} from {source_url[:60]}')

        if source_type == 'pdf':
            text = extract_text_from_pdf(content)
        else:
            raw  = extract_text_from_html(content)
            text = [(1, [(raw, 0.0, 0.0, 1.0, 1.0)])] if raw else None

        if not text:
            log.warning(f'rerun_ingest: text extraction returned nothing for {paper_id}')
            return

        passages = chunk_text(text, paper_id)
        if not passages:
            log.warning(f'rerun_ingest: no passages for {paper_id}')
            return

        ok = write_passages_to_db(paper_id, passages, bibcode, source_url)
        log.info(f'rerun_ingest done: {len(passages)} passages, db_ok={ok}')

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'message': 'Extraction started in background — check logs for progress'})

# ── Paper add routes ─────────────────────────────────────────────────────────

def _is_duplicate(conn, library_id, title, authors, year, journal, volume, pages, doi, bibcode):
    """
    Holistic duplicate detection using a scoring system.
    Returns (is_duplicate, existing_bibkey) or (False, None).
    """
    def norm(s):
        return re.sub(r'\W+', '', (s or '').lower().strip())

    # Fast path: exact unique identifiers
    if bibcode:
        row = conn.execute(
            'SELECT id, bibkey FROM papers WHERE library_id=? AND bibcode=?',
            (library_id, bibcode)
        ).fetchone()
        if row: return True, row['bibkey']

    if doi:
        row = conn.execute(
            'SELECT id, bibkey FROM papers WHERE library_id=? AND doi=?',
            (library_id, doi)
        ).fetchone()
        if row: return True, row['bibkey']

    if not title:
        return False, None

    candidates = conn.execute(
        '''SELECT id, bibkey, title, authors, year, journal, volume, pages
           FROM papers WHERE library_id=?''',
        (library_id,)
    ).fetchall()

    norm_title   = norm(title)
    norm_author  = norm((authors or '').split(';')[0].split(',')[0])
    norm_journal = norm(journal)
    new_year     = str(year or '').strip()
    norm_vol     = norm(volume)
    norm_page    = norm((pages or '').split('-')[0])

    for row in candidates:
        score = 0
        nt = norm(row['title'])
        if norm_title and nt:
            if norm_title == nt:               score += 50
            elif norm_title in nt or nt in norm_title: score += 30
        na = norm((row['authors'] or '').split(';')[0].split(',')[0])
        if norm_author and na == norm_author:  score += 20
        if new_year and str(row['year'] or '').strip() == new_year: score += 15
        nj = norm(row['journal'])
        if norm_journal and nj == norm_journal: score += 10
        if norm_vol  and norm(row['volume']) == norm_vol:  score += 5
        np_ = norm((row['pages'] or '').split('-')[0])
        if norm_page and np_ == norm_page:     score += 5
        if score >= 70:
            return True, row['bibkey']

    return False, None

@app.route('/api/papers/add-manual', methods=['POST'])
@gas_auth_required
def add_paper_manual():
    raw = request.get_data(as_text=True)
    import re as _re
    bk_match = _re.search(r'"bibkey"\s*:\s*"([^"]+)"', raw)
    """Add paper from manually entered fields."""
    data    = request.json or {}
    title   = (data.get('title') or '').strip()
    authors = (data.get('authors') or '').strip()
    year    = str(data.get('year') or '').strip()
    if not title or not authors or not year:
        return err('title, authors, and year required')

    conn = get_db_connection()
    # Prefer explicit library from client; fall back to server CONFIG
    explicit_lib = (data.get('library') or '').strip()
    if explicit_lib:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (explicit_lib,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
    else:
        library_id, _ = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)

    journal = (data.get('journal') or '').strip()
    volume  = (data.get('volume') or '').strip()
    pages   = (data.get('pages') or '').strip()
    doi     = (data.get('doi') or '').strip()
    bibcode = (data.get('bibcode') or '').strip()
    pdf_url = (data.get('pdf_url') or '').strip()
    pubtype = (data.get('pubtype') or 'article').strip()
    abstract = (data.get('abstract') or '').strip()
    bibtex   = (data.get('bibtex')   or '').strip()
    tags     = (data.get('tags')     or '').strip()

    # ── Duplicate check ───────────────────────────────────────────────────
    is_dup, dup_bibkey = _is_duplicate(
        conn, library_id, title, authors, year, journal, volume, pages, doi, bibcode
    )
    if is_dup:
        conn.close()
        return jsonify({'ok': True, 'duplicate': True, 'bibkey': dup_bibkey,
                        'message': f'Already in library as {dup_bibkey}'})

    # ── Bibkey: use client-supplied key if present (GAS _adsDocToPaper
    #    builds the correct full key e.g. joshi+2022mnras510_5854).
    #    Only generate server-side for manual entries with no bibkey. ─────
    def _ascii_only(s):
        s = _ucd.normalize('NFKD', s)
        s = ''.join(c for c in s if not _ucd.combining(c))
        return re.sub(r'[^a-z0-9+_]', '', s.lower())

    client_bibkey = _ascii_only((data.get('bibkey') or '').strip())
    if client_bibkey:
        bibkey = client_bibkey
    else:
        # Server-side fallback: construct full BibMan-format bibkey
        booktitle = (data.get('booktitle') or '').strip()
        bibkey = _make_bibkey(authors, year, journal, volume, pages, pubtype, booktitle)
        if not bibkey:
            bibkey = f'ref{year}'

    base_key = bibkey
    suffix   = 0
    while conn.execute(
        'SELECT id FROM papers WHERE library_id=? AND bibkey=?',
        (library_id, bibkey)
    ).fetchone():
        suffix += 1
        if suffix > 25:
            bibkey = f'{base_key}_{uuid.uuid4().hex[:4]}'
            break
        bibkey = f'{base_key}{chr(96+suffix)}'

    identifiers = data.get('identifiers', [])
    user_id  = get_user_id()
    paper_id = str(uuid.uuid4())
    conn.execute('''
        INSERT INTO papers
            (id,library_id,bibkey,title,authors,year,journal,
             volume,pages,pubtype,bibcode,doi,pdf_url,bibtex,
             abstract,tags,added_by,read_status,pdf_extracted)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (paper_id, library_id, bibkey, title, authors, year,
          journal, volume, pages, pubtype, bibcode, doi, pdf_url, bibtex,
          abstract, tags, user_id, 'unread', 0))
    conn.commit()
    conn.close()

    _, gemini_key = get_request_tokens()
    if pdf_url or bibcode or identifiers:
        threading.Thread(
            target=ingest_paper_background,
            args=(paper_id, bibcode, identifiers, '', gemini_key),
            daemon=True
        ).start()

    return jsonify({'ok': True, 'bibkey': bibkey, 'paper_id': paper_id}), 201

@app.route('/api/papers/extract-metadata', methods=['POST'])
@gas_auth_required
def extract_metadata():
    """
    Fetch an arbitrary PDF or HTML URL server-side, extract text from the
    first 3 pages, then ask Gemini to identify title/authors/year/journal/
    DOI/arXiv ID. Returns structured metadata JSON. Does NOT save anything —
    Called by GAS doPost extract_and_preview action when no identifier was
    found in the URL or page meta tags.
    """
    data = request.json or {}
    url  = (data.get('url') or '').strip()
    _, gemini_key = get_request_tokens()

    if not url:
        return err('url required')
    if not gemini_key:
        return err('Gemini key required for metadata extraction')

    fetch_headers = {'User-Agent': 'Mozilla/5.0 (compatible; BibMan/1.0)'}
    try:
        resp = requests.get(url, headers=fetch_headers, timeout=20,
                            allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        return err(f'Could not fetch URL: {e}')

    content_type = resp.headers.get('content-type', '').lower()
    is_pdf = 'pdf' in content_type or url.lower().split('?')[0].endswith('.pdf')

    extracted_text = ''
    if is_pdf:
        # Reuse the existing extract_text_from_pdf which tries PyMuPDF, pdftotext, pypdf
        pages = extract_text_from_pdf(resp.content)
        if pages:
            # Take first 3 pages of text
            extracted_text = '\n'.join(
                text for pn, blocks in pages[:3]
                for text, *_ in blocks
            )
        if not extracted_text.strip():
            return err('PDF text extraction failed — may be image-only or scanned')
    else:
        # Reuse existing HTML extractor
        extracted_text = extract_text_from_html(resp.content) or ''
        if not extracted_text:
            # Fallback: strip tags manually
            t = re.sub(r'<script[^>]*>.*?</script>', '', resp.text,
                       flags=re.DOTALL | re.IGNORECASE)
            t = re.sub(r'<style[^>]*>.*?</style>',  '', t,
                       flags=re.DOTALL | re.IGNORECASE)
            t = re.sub(r'<[^>]+>', ' ', t)
            extracted_text = re.sub(r'\s+', ' ', t).strip()[:4000]

    if not extracted_text.strip():
        return err('No text could be extracted from this URL')

    prompt = (
        'Extract bibliographic metadata from the text below. '
        'Return ONLY a JSON object with these exact keys (null if unknown): '
        'title, authors (semicolon-separated, "Last, F." format), '
        'year (integer or null), journal, doi, arxiv_id, volume, pages\n\n'
        'Text:\n' + extracted_text[:3000] +
        '\n\nJSON only — no markdown fences, no explanation:'
    )

    gemini_url = (
        'https://generativelanguage.googleapis.com/v1beta/'
        f'{get_request_models()[1]}:generateContent'
    )
    try:
        gr = requests.post(gemini_url, headers=_gemini_headers(gemini_key), json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 400},
        }, timeout=25)
        gr.raise_for_status()
        raw_text = gr.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        raw_text = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw_text, flags=re.S)
        meta = json.loads(raw_text.strip())
    except Exception as e:
        return err(f'Gemini metadata extraction failed: {e}')

    meta['source']     = 'gemini'
    meta['source_url'] = url
    return jsonify(meta)

# ── PDF proxy (for non-arXiv, non-Drive papers only) ─────────────────────────
@app.route('/api/papers/<paper_id>/pdf')
@gas_auth_required
def get_paper_pdf(paper_id):
    """
    Proxy PDF bytes for papers that can't be fetched directly by the browser.
    For arXiv papers: GAS returns the arXiv URL, PDF.js fetches directly via
    Cloudflare Worker (zero egress). This route handles Drive and publisher URLs.
    """
    conn  = get_db_connection()
    paper = conn.execute('SELECT * FROM papers WHERE id=?', (paper_id,)).fetchone()
    conn.close()
    if not paper:
        return err('Paper not found', 404)

    paper_dict = dict(paper)
    ads_token, _ = get_request_tokens()

    # Use stored source URL first (same version as was ingested)
    source_url = (paper_dict.get('content_source_url') or '').strip()
    if source_url and not source_url.startswith(('drive:', 'ads:')):
        if not source_url.startswith('https://arxiv.org/'):
            # Non-arXiv URL — proxy it
            fetched, ftype = fetch_url_content(source_url)
            if fetched and ftype == 'pdf':
                return Response(fetched, mimetype='application/pdf',
                                headers={'Content-Disposition': 'inline'})

    content, source_type, _, _nfp = fetch_content_for_paper(paper_dict, ads_token)
    if not content:
        return err('PDF not available', 404)
    if source_type == 'pdf':
        return Response(content, mimetype='application/pdf',
                        headers={'Content-Disposition': 'inline'})
    if isinstance(content, bytes):
        content = content.decode('utf-8', errors='replace')
    return Response(content, mimetype='text/html')

# ── PDF source info (tells GAS which URL to use for direct fetch) ─────────────
@app.route('/api/papers/<paper_id>/pdf-info')
@gas_auth_required
def get_pdf_info(paper_id):
    """
    Returns the PDF source type and URL so GAS can decide how to deliver it:
    - arxiv: GAS passes URL to Cloudflare Worker → PDF.js fetches directly
    - drive: GAS generates a short-lived OAth URL (googleapis.com/drive/v3/{id}?alt=media)
             and returns just the URL → PDF.js fetches directy (GAS not in bytes path)
    - proxy: GAS calls /api/papers/<id>/pdf and relays bytes
    """
    conn  = get_db_connection()
    paper = conn.execute(
        'SELECT pdf_url, file_id, content_source_url FROM papers WHERE id=?',
        (paper_id,)
    ).fetchone()
    conn.close()
    if not paper:
        return err('Paper not found', 404)

    source_url = (paper['content_source_url'] or paper['pdf_url'] or '').strip()
    file_id    = (paper['file_id'] or '').strip()

    if file_id or 'drive.google.com' in source_url:
        # Extract Drive file ID
        fid = file_id
        if not fid:
            m = re.search(r'/(?:file/d|open\?id=)([a-zA-Z0-9_-]{20,})', source_url)
            fid = m.group(1) if m else ''
        return jsonify({'type': 'drive', 'file_id': fid})

    if 'arxiv.org' in source_url:
        return jsonify({'type': 'arxiv', 'url': source_url})

    if source_url:
        return jsonify({'type': 'proxy', 'url': f'/api/papers/{paper_id}/pdf'})

    return jsonify({'type': 'none'})

# ── Annotations ───────────────────────────────────────────────────────────────
@app.route('/api/annotations', methods=['POST'])
@gas_auth_required
def create_annotation():
    data = request.json or {}
    if not data.get('paper_id'):
        return err('paper_id required')
    if not data.get('annotation_type'):
        data['annotation_type'] = 'passage' if data.get('coords') else 'paper'

    ann_id  = str(uuid.uuid4())
    user_id = get_user_id()
    _, gemini_key = get_request_tokens()
    conn    = get_db_connection()

    # Support both old schema (coords/quote/user_note) and new schema (x1/y1/x2/y2/text)
    note_text  = data.get('user_note') or data.get('text') or ''
    quote_text = data.get('quote') or ''
    coords_raw = data.get('coords')  # JSON string or None
    page_num   = data.get('page_number', 1)

    # Extract first rect page number from coords if not provided
    if coords_raw and not data.get('page_number'):
        try:
            rects = json.loads(coords_raw)
            if isinstance(rects, list) and rects:
                page_num = rects[0].get('page', 1)
        except Exception:
            pass

    conn.execute('''
        INSERT INTO annotations
            (id, paper_id, annotation_type, user_note, quote,
             coords, username)
        VALUES (?,?,?,?,?,?,?)
    ''', (ann_id, data['paper_id'], data['annotation_type'],
          note_text, quote_text, coords_raw, user_id))
    conn.commit()
    conn.close()

    # Embed note text for search
    if note_text:
        threading.Thread(
            target=embed_annotation_background,
            args=(ann_id, note_text, data['paper_id'], gemini_key),
            daemon=True
        ).start()
    return jsonify({'ok': True, 'id': ann_id}), 201

@app.route('/api/annotations/<ann_id>', methods=['PATCH'])
@gas_auth_required
def update_annotation(ann_id):
    data    = dict(request.json or {})
    if 'text' in data and 'user_note' not in data:  # dashboard sends both; table only has user_note
        data['user_note'] = data['text']
    allowed = {'user_note'}
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return err('No valid fields')
    sets   = ', '.join(f'{k}=?' for k in updates)
    values = list(updates.values()) + [ann_id]
    _, gemini_key = get_request_tokens()
    conn   = get_db_connection()
    conn.execute(f'UPDATE annotations SET {sets} WHERE id=?', values)
    conn.commit()
    # Re-embed if note text was updated (either field name)
    new_text = updates.get('user_note') or updates.get('text')
    if new_text:
        ann_row = conn.execute(
            'SELECT paper_id FROM annotations WHERE id=?', (ann_id,)
        ).fetchone()
        paper_id = ann_row['paper_id'] if ann_row else ''
        conn.close()
        threading.Thread(
            target=embed_annotation_background,
            args=(ann_id, new_text, paper_id, gemini_key),
            daemon=True
        ).start()
    else:
        conn.close()
    return jsonify({'ok': True})

@app.route('/api/annotations/<ann_id>', methods=['DELETE'])
@gas_auth_required
def delete_annotation(ann_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM annotations WHERE id=?', (ann_id,))
    try:
        conn.execute('DELETE FROM annotations_fts WHERE annotation_id=?', (ann_id,))
    except Exception:
        pass
    try:
        conn.execute('DELETE FROM vec_annotations WHERE annotation_id=?', (ann_id,))
    except Exception:
        pass
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/annotations/<ann_id>/flags', methods=['PATCH'])
@gas_auth_required
def update_annotation_flags(ann_id):
    data = request.json or {}
    sets = []
    vals = []
    for flag in ('flag_key_point', 'flag_follow_up', 'flag_pinned'):
        if flag in data:
            sets.append(f'{flag}=?')
            vals.append(int(bool(data[flag])))
    if not sets:
        return err('No flag fields')
    vals.append(ann_id)
    conn = get_db_connection()
    conn.execute(f'UPDATE annotations SET {", ".join(sets)} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# ── Search ────────────────────────────────────────────────────────────────────
@app.route('/api/search/venn', methods=['POST'])
@gas_auth_required
def venn_search():
    from collections import defaultdict
    data            = request.json or {}
    queries         = data.get('queries', [])
    global_excludes = data.get('global_excludes', [])
    use_synonyms = data.get('use_synonyms', True)
    use_semantic = data.get('use_semantic', True)
    max_results  = int(data.get('max_results', 200))
    everyone     = bool(data.get('everyone', True))
    current_user = (data.get('current_user') or '').strip()
    if not queries:
        return err('queries required')

    conn = get_db_connection()
    # Prefer explicit library from client; fall back to server CONFIG
    explicit_lib = data.get('library', '').strip()
    if explicit_lib:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (explicit_lib,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
        log.info(f'venn_search: using explicit library={explicit_lib} id={library_id}')
    else:
        library_id, explicit_lib = get_current_library_id(conn)
        log.info(f'venn_search: using CONFIG library={explicit_lib} id={library_id}')
    if not library_id:
        conn.close()
        return jsonify({'upset_data': [], 'merged_results': [], 'papers_list': [],
                        'strict_passages': [], 'paper_results': [], 'highlight_terms': [], 'total': 0})

    username = get_user_id()

    # Load synonyms
    syn_rows = conn.execute('''
        SELECT term_a_norm, term_b_norm FROM synonyms
        WHERE library_id=? AND is_suppressed=0
    ''', (library_id,)).fetchall()
    synonyms = {}
    for r in syn_rows:
        a, b = r['term_a_norm'], r['term_b_norm']
        synonyms.setdefault(a, set()).add(b)
        synonyms.setdefault(b, set()).add(a)

    def _fts_quote(t):
        """Quote one term for an FTS5 MATCH so characters like + / * - are taken literally."""
        return '"' + t.replace('"', '""') + '"'

    def _fts_useful(t):
        """A synonym is worth searching only if FTS would see a phrase or a token of 3+ characters.
        (Full-text search drops punctuation, so 'C+' becomes 'c' and would match every lone 'c'.)"""
        toks = re.findall(r'[a-z0-9]+', t.lower())
        return len(toks) > 1 or (len(toks) == 1 and len(toks[0]) >= 3)

    def expand_terms(q):
        """Return (include_terms_set, exclude_term, fts_query_string, skip_semantic).

        Quoting behavior:
          "phrase"  — verbatim: exact FTS phrase only, no synonyms, no semantic
          phrase    — smart: FTS phrase + whole-phrase synonyms + semantic
          word      — full: word synonyms (OR) + semantic

        Excludes are handled globally via global_excludes, not per-circle.
        """
        q = q.strip()
        include_raw = q

        # Detect user-supplied quotes → verbatim mode
        verbatim = include_raw.startswith('"') and include_raw.endswith('"') and len(include_raw) > 2
        if verbatim:
            include_raw = include_raw[1:-1].strip()  # strip the quotes

        words = re.findall(r'[a-z0-9]+', include_raw.lower())
        is_phrase = len(words) > 1

        if verbatim:
            # Strict verbatim — exact FTS phrase only, no synonyms, no semantic
            fts = _fts_quote(include_raw.lower())
            expanded = {include_raw.lower()}  # highlight the exact phrase, not its separate words
            return expanded, '', fts, True  # skip_semantic=True

        if is_phrase:
            # Smart phrase — FTS phrase + whole-phrase synonyms only
            phrase_key = include_raw.lower()
            phrase_synonyms = synonyms.get(phrase_key, set())
            fts = _fts_quote(phrase_key)
            valid_syns = []
            if use_synonyms and phrase_synonyms:
                valid_syns = sorted(
                    {t for t in phrase_synonyms if len(t) >= 2 and _fts_useful(t)},
                    key=len
                )[:8]
                if valid_syns:
                    fts += ' OR ' + ' OR '.join(
                        _fts_quote(t) for t in valid_syns
                    )
            # Highlight the phrase and the synonyms actually searched, not its separate words
            # (highlighting a lone "c" from "C II" would mark every word starting with c).
            expanded = {phrase_key, *valid_syns}
            return expanded, '', fts, False  # skip_semantic=False

        else:
            # Single word — word-level synonym expansion + semantic
            expanded = set(words)
            for w in words:
                if use_synonyms:
                    expanded.update(synonyms.get(w, set()))
            valid = {t for t in expanded if len(t) >= 3}
            if not valid:
                valid = expanded
            original_words = set(words)
            synonym_words = {t for t in valid - original_words if _fts_useful(t)}
            synonym_list = sorted(synonym_words, key=len)[:max(0, 12 - len(original_words))]
            valid_list = sorted(original_words) + synonym_list
            fts = ' OR '.join(_fts_quote(t) for t in valid_list)
            return set(valid_list), '', fts, False  # highlight exactly what was searched

    ads_token, gemini_key = get_request_tokens()

    # Parse and expand each query
    expanded_queries = [expand_terms(q) for q in queries]
    highlight_terms  = [list(inc) for inc, _, _, _ in expanded_queries]

    # passage_id -> set of circle indices that found it
    passage_circle_map  = defaultdict(set)
    passage_to_paper    = {}          # passage_id -> paper_id

    PASSAGE_COLLAPSE_THRESHOLD = 8

    exact_pids_by_circle   = {}  # ci -> set of passage IDs matching original terms
    synonym_pids_by_circle = {}  # ci -> set of passage IDs matching via synonyms only
    for ci, (include_terms, _exc, fts, skip_semantic) in enumerate(expanded_queries):
        if not fts.strip():
            continue
        # ── FTS ──────────────────────────────────────────────────────────
        # Run exact terms query to track which passages match original terms
        try:
            # Full expanded FTS (includes synonyms)
            rows = conn.execute('''
                SELECT pa.id, pp.id AS paper_id
                FROM passages_fts
                JOIN passages pa ON pa.rowid = passages_fts.rowid
                JOIN papers pp   ON pp.id = pa.paper_id
                WHERE passages_fts MATCH ? AND pp.library_id=?
                LIMIT 2000
            ''', (fts, library_id)).fetchall()
            for row in rows:
                pid = row['id']
                passage_circle_map[pid].add(ci)
                passage_to_paper[pid] = row['paper_id']
        except Exception as e:
            log.warning(f'FTS circle {ci} failed: {e}')

        # ── Hybrid semantic search (USearch + sqlite-vec) ─────────────────────
        if use_semantic and not skip_semantic and USEARCH_INDEX is not None:
            q_vec = embed_query(queries[ci], gemini_key)
            if q_vec:
                # Unpack bytes to list, then truncate to 768 dims (MRL) and convert to numpy
                full_vec = struct.unpack(f'{len(q_vec)//4}f', q_vec)
                q_vec_truncated = np.array(full_vec[:768], dtype=np.float32)
                # Query USearch for bulk of library
                try:
                    matches = USEARCH_INDEX.search(q_vec_truncated, 50)  # Reduced to 50 for speed on e2-micro
                    # Apply score threshold — filter weak semantic matches
                    search_ids = []
                    for key, distance in zip(matches.keys, matches.distances):
                        similarity = 1.0 - float(distance)
                        if similarity >= 0.75:
                            search_ids.append(key)
                    
                    # Convert search_ids back to passage_ids
                    if search_ids:
                        ph = ','.join('?' * len(search_ids))
                        rows = conn.execute(f'''
                            SELECT pa.id AS passage_id, pa.paper_id
                            FROM passages pa
                            WHERE pa.search_id IN ({ph})
                        ''', list(map(int, search_ids))).fetchall()
                        
                        for row in rows:
                            pid = row['passage_id']
                            passage_circle_map[pid].add(ci)
                            passage_to_paper[pid] = row['paper_id']
                except Exception as e:
                    log.warning(f'USearch circle {ci} failed: {e}')

    # ── Annotation search ────────────────────────────────────────────────────
    ann_circle_map = defaultdict(set)  # annotation_id -> set of circle indices
    ann_row_cache  = {}                # annotation_id -> row data

    for ci, (include_terms, _exc, fts, skip_semantic) in enumerate(expanded_queries):
        if not fts.strip():
            continue
        try:
            if everyone:
                ann_rows = conn.execute('''
                    SELECT a.id, a.paper_id, a.passage_id, a.user_note,
                           a.coords, a.username,
                           pp.bibkey, pp.year, pp.title, pp.authors, pp.journal
                    FROM annotations_fts af
                    JOIN annotations a ON a.id = af.annotation_id
                    JOIN papers pp ON pp.id = a.paper_id
                    WHERE annotations_fts MATCH ? AND pp.library_id=?
                    AND a.user_note IS NOT NULL AND a.user_note != ''
                ''', (fts, library_id)).fetchall()
            else:
                ann_rows = conn.execute('''
                    SELECT a.id, a.paper_id, a.passage_id, a.user_note,
                           a.coords, a.username,
                           pp.bibkey, pp.year, pp.title, pp.authors, pp.journal
                    FROM annotations_fts af
                    JOIN annotations a ON a.id = af.annotation_id
                    JOIN papers pp ON pp.id = a.paper_id
                    WHERE annotations_fts MATCH ? AND pp.library_id=?
                    AND a.username = ?
                    AND a.user_note IS NOT NULL AND a.user_note != ''
                ''', (fts, library_id, current_user)).fetchall()
            for row in ann_rows:
                ann_id = row['id']
                ann_circle_map[ann_id].add(ci)
                if ann_id not in ann_row_cache:
                    ann_row_cache[ann_id] = row
        except Exception as e:
            log.warning(f'Annotation search circle {ci} failed: {e}')

    # Build annotation_results with correct multi-circle membership
    annotation_results = []
    for ann_id, circles in ann_circle_map.items():
        row = ann_row_cache[ann_id]
        coords = []
        if row['coords']:
            try:
                c = json.loads(row['coords'])
                coords = c if isinstance(c, list) else [c]
            except Exception:
                pass
        page_num = coords[0].get('page', 1) if coords else 1
        if coords:
            # Get bounding box spanning all rects
            if 'x0' in coords[0]:  # old format
                x1 = min(c.get('x0', 0) for c in coords)
                y1 = min(c.get('y0', 0) for c in coords)
                x2 = max(c.get('x1', 1) for c in coords)
                y2 = max(c.get('y1', 1) for c in coords)
            else:  # new format
                x1 = min(c.get('x1', 0) for c in coords)
                y1 = min(c.get('y1', 0) for c in coords)
                x2 = max(c.get('x2', 1) for c in coords)
                y2 = max(c.get('y2', 1) for c in coords)
        else:
            x1, y1, x2, y2 = 0, 0, 1, 1

        annotation_results.append({
            'id':           ann_id,
            'paper_id':     row['paper_id'],
            'passage_id':   row['passage_id'],
            'text':         row['user_note'],
            'bibkey':       row['bibkey'],
            'year':         row['year'],
            'title':        row['title'],
            'authors':      row['authors'],
            'journal':      row['journal'],
            'page_number':  page_num,
            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2,
            'username':     row['username'],
            'circles':      sorted(circles),
            'result_type':  'annotation',
            'semantic_match': False,
            'synonym_match':  False,
        })    

    # Apply global excludes - post-filter on result set only
    if global_excludes and passage_circle_map:
        pids = list(passage_circle_map.keys())
        ph = ','.join('?' * len(pids))
        exclude_pids = set()
        for term in global_excludes:
            term_norm = re.sub(r'[^a-z0-9 ]', ' ', term.lower()).strip()
            if not term_norm:
                continue
            try:
                rows = conn.execute(f'''
                    SELECT pa.id FROM passages pa
                    JOIN passages_fts ON passages_fts.rowid = pa.rowid
                    WHERE pa.id IN ({ph}) AND passages_fts MATCH ?
                ''', pids + [term_norm]).fetchall()
                exclude_pids.update(r['id'] for r in rows)
            except Exception:
                pass
        for pid in exclude_pids:
            passage_circle_map.pop(pid, None)
            passage_to_paper.pop(pid, None)

    all_passage_ids = set(passage_circle_map.keys())

    if not all_passage_ids:
        conn.close()
        return jsonify({'upset_data': [], 'merged_results': [], 'papers_list': [],
                        'strict_passages': [], 'paper_results': [], 'highlight_terms': highlight_terms,
                        'total': 0})

    # Build upset_data (one entry per passage, with circle membership)
    upset_data = []
    if all_passage_ids:
        ph    = ','.join('?' * len(all_passage_ids))
        rows  = conn.execute(f'''
            SELECT pa.id, pp.id AS paper_id, pp.bibkey, pp.year
            FROM passages pa
            JOIN papers pp ON pp.id = pa.paper_id
            WHERE pa.id IN ({ph})
        ''', list(all_passage_ids)).fetchall()
        for row in rows:
            upset_data.append({
                'id':       row['id'],
                'paper_id': row['paper_id'],
                'bibkey':   row['bibkey'],
                'year':     row['year'],
                'circles':  sorted(passage_circle_map.get(row['id'], [])),
            })

    # Group passages by paper and find best intersection signature
    paper_best_sig = {}  # paper_id -> tuple of sorted circle indices
    paper_sig_passages = defaultdict(list)  # (paper_id, sig) -> [passage_ids]
    for pid, circles in passage_circle_map.items():
        paper_id = passage_to_paper[pid]
        sig = tuple(sorted(circles))
        paper_sig_passages[(paper_id, sig)].append(pid)
        existing = paper_best_sig.get(paper_id, ())
        if len(sig) > len(existing) or (len(sig) == len(existing) and len(paper_sig_passages[(paper_id, sig)]) > len(paper_sig_passages.get((paper_id, existing), []))):
            paper_best_sig[paper_id] = sig

    # Decide passage vs paper mode per paper
    passage_ids_to_fetch = []
    paper_ids_to_fetch   = []
    for paper_id, best_sig in paper_best_sig.items():
        passages_at_sig = paper_sig_passages.get((paper_id, best_sig), [])
        if len(passages_at_sig) > PASSAGE_COLLAPSE_THRESHOLD:
            paper_ids_to_fetch.append(paper_id)
        else:
            passage_ids_to_fetch.extend(passages_at_sig)

    # Cap passage_ids_to_fetch to max_results before expensive fetch
    # Reserve slots for paper_results (collapsed papers)
    reserved = min(len(paper_ids_to_fetch), max_results // 4)
    passage_cap = max_results - reserved
    if len(passage_ids_to_fetch) > passage_cap:
        passage_ids_to_fetch = passage_ids_to_fetch[:passage_cap]


    # Accurate labeling: check only final result passages against FTS
    if passage_ids_to_fetch:
        ph2 = ','.join('?' * len(passage_ids_to_fetch))
        for ci in range(len(queries)):
            inc, exc, fts, _skip = expanded_queries[ci]
            orig_words = re.findall(r'[a-z0-9]+', queries[ci].lower())
            orig_fts   = ' '.join(w for w in orig_words) if orig_words else ''  # space = AND in FTS5
            exact_pids_by_circle[ci] = set()

            if orig_fts:
                exact_rows = conn.execute(f'''
                    SELECT pa.id FROM passages pa
                    JOIN passages_fts ON passages_fts.rowid = pa.rowid
                    WHERE pa.id IN ({ph2}) AND passages_fts MATCH ?
                ''', list(passage_ids_to_fetch) + [orig_fts]).fetchall()
                exact_pids_by_circle[ci] = {r['id'] for r in exact_rows}
            fts_rows = conn.execute(f'''
                SELECT pa.id FROM passages pa
                JOIN passages_fts ON passages_fts.rowid = pa.rowid
                WHERE pa.id IN ({ph2}) AND passages_fts MATCH ?
            ''', list(passage_ids_to_fetch) + [fts]).fetchall()
            synonym_pids_by_circle[ci] = {r['id'] for r in fts_rows} - exact_pids_by_circle[ci]

    # Fetch passage details
    strict_results = []

    if passage_ids_to_fetch:
        ph   = ','.join('?' * len(passage_ids_to_fetch))
        rows = conn.execute(f'''
            SELECT pa.id, pa.text, pa.page_number, pa.x1, pa.y1, pa.x2, pa.y2,
                   pp.id AS paper_id, pp.bibkey, pp.year, pp.title, pp.authors, pp.journal,
                   a.id as annotation_id,
                   COALESCE(a.user_note, '') as user_note,
                   0 as bookmarked
            FROM passages pa
            JOIN papers pp ON pp.id = pa.paper_id
            LEFT JOIN annotations a ON a.passage_id = pa.id
                AND a.user_note IS NOT NULL AND a.user_note != ''
                AND (? OR a.username = ?)
            WHERE pa.id IN ({ph})
            ORDER BY pp.bibkey, pa.page_number
        ''', [1 if everyone else 0, current_user] + passage_ids_to_fetch).fetchall()

        # Labeling uses pre-computed exact_pids_by_circle and synonym_pids_by_circle

        seen = set()
        for row in rows:
            if row['id'] in seen:
                continue
            seen.add(row['id'])
            d = dict(row)
            d['circles']        = sorted(passage_circle_map.get(row['id'], []))
            pid = row['id']
            circles = sorted(passage_circle_map.get(pid, []))
            is_semantic = False
            is_synonym  = False
            for ci in circles:
                if pid in exact_pids_by_circle.get(ci, set()):
                    pass      # keyword match, no badge
                elif pid in synonym_pids_by_circle.get(ci, set()):
                    is_synonym  = True
                else:
                    is_semantic = True
            d['semantic_match'] = is_semantic
            d['synonym_match']  = is_synonym
            d['result_type']    = 'passage'
            strict_results.append(d)

    # Fetch paper details (collapsed)
    paper_results = []
    if paper_ids_to_fetch:
        ph   = ','.join('?' * len(paper_ids_to_fetch))
        rows = conn.execute(f'''
            SELECT pp.id AS paper_id, pp.bibkey, pp.year, pp.title, pp.authors, pp.journal,
                   COALESCE(a.user_note, '') as user_note
            FROM papers pp
            LEFT JOIN annotations a ON a.paper_id = pp.id AND a.annotation_type='paper'
            WHERE pp.id IN ({ph})
            GROUP BY pp.id
            ORDER BY pp.bibkey
        ''', paper_ids_to_fetch).fetchall()
        seen = set()
        for row in rows:
            if row['paper_id'] in seen:
                continue
            seen.add(row['paper_id'])
            d = dict(row)
            d['circles']          = sorted(paper_best_sig.get(row['paper_id'], ()))
            d['multiple_passages'] = True
            d['result_type']       = 'paper'
            paper_results.append(d)

    # Build merged list
    merged = strict_results + paper_results
    merged.sort(key=lambda r: (r.get('bibkey', ''), r.get('page_number', 0) or 0))

    conn.close()
    total = len(merged)
    if max_results and len(merged) > max_results:
        merged = merged[:max_results]
        total  = len(merged)

    # Add annotation results after cap -- always included regardless of max_results
    merged = merged + annotation_results

    # Build papers list AFTER annotations are added to merged
    seen_papers = {}
    for r in merged:
        pid = r.get('paper_id')
        if pid and pid not in seen_papers:
            seen_papers[pid] = {
                'paper_id': pid, 'bibkey': r.get('bibkey', ''),
                'year': r.get('year', ''), 'title': r.get('title', ''),
                'authors': r.get('authors', ''), 'journal': r.get('journal', ''),
                'user_note': r.get('user_note', ''), 'circles': r.get('circles', []),
            }
    papers_list = sorted(seen_papers.values(), key=lambda r: r.get('bibkey', ''))

    # Trim papers_list and paper_results to only papers in merged results
    merged_paper_ids = {r['paper_id'] for r in merged}
    papers_list   = [p for p in papers_list   if p['paper_id'] in merged_paper_ids]
    paper_results = [p for p in paper_results if p['paper_id'] in merged_paper_ids]

    # Trim upset_data to only passages in merged_results
    merged_ids = {r['id'] for r in merged if r.get('result_type') == 'passage'}
    merged_paper_ids_for_upset = {r['paper_id'] for r in merged if r.get('result_type') == 'paper'}
    upset_data = [u for u in upset_data if u['id'] in merged_ids or u['paper_id'] in merged_paper_ids_for_upset]

    # Add annotation results to upset_data so bar counts include them
    for a in annotation_results:
        upset_data.append({
            'id':       a['id'],
            'paper_id': a['paper_id'],
            'bibkey':   a['bibkey'],
            'year':     a['year'],
            'circles':  a['circles'],
        })

    log.info(f'venn_search done: {total} results ({len(strict_results)} passages, {len(paper_results)} papers)')
    return jsonify({
        'strict_passages':    [],
        'paper_results':      paper_results,
        'merged_results':     merged,
        'papers_list':        papers_list,
        'highlight_terms':    highlight_terms,
        'upset_data':         upset_data,
        'annotation_results': annotation_results,
        'total':              total,
        'semantic_skipped':   not bool(gemini_key) or USEARCH_INDEX is None,
    })

@app.route('/api/search/suggestions')
@gas_auth_required
def search_suggestions():
    q = (request.args.get('q') or '').strip().lower()
    if len(q) < 2:
        return jsonify([])
    conn = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    rows = conn.execute('''
        SELECT term FROM corpus_terms
        WHERE library_id=? AND term LIKE ?
        ORDER BY frequency DESC LIMIT 20
    ''', (library_id, f'{q}%')).fetchall()
    conn.close()
    return jsonify([r['term'] for r in rows])

@app.route('/api/synonyms')
@gas_auth_required
def get_synonyms():
    conn = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    rows = conn.execute('''
        SELECT id, term_a, term_b, source, confidence,
               is_suppressed, is_suspicious, notes
        FROM synonyms WHERE library_id=?
        ORDER BY is_suppressed ASC, source, term_a
    ''', (library_id,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

@app.route('/api/synonyms', methods=['POST'])
@gas_auth_required
def add_synonym():
    data   = request.json or {}
    term_a = (data.get('term_a') or '').strip()
    term_b = (data.get('term_b') or '').strip()
    if not term_a or not term_b:
        return err('term_a and term_b required')
    conn = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    a_norm = normalize_for_db(term_a)
    b_norm = normalize_for_db(term_b)
    syn_id = str(uuid.uuid4())
    try:
        conn.execute('''
            INSERT INTO synonyms
                (id,library_id,term_a,term_b,term_a_norm,term_b_norm,
                 source,confidence,is_suppressed)
            VALUES (?,?,?,?,?,?,?,?,?)
        ''', (syn_id, library_id, term_a, term_b, a_norm, b_norm,
              data.get('source','manual'), data.get('confidence', 1.0), 0))
        conn.commit()
    except Exception as e:
        conn.close()
        return err(str(e))
    conn.close()
    return jsonify({'ok': True, 'id': syn_id}), 201

@app.route('/api/synonyms/<syn_id>/approve', methods=['POST'])
@gas_auth_required
def approve_synonym(syn_id):
    conn = get_db_connection()
    conn.execute('UPDATE synonyms SET is_suppressed=0 WHERE id=?', (syn_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/synonyms/<syn_id>', methods=['DELETE'])
@gas_auth_required
def delete_synonym(syn_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM synonyms WHERE id=?', (syn_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/synonyms/import-defaults', methods=['POST'])
@gas_auth_required
def import_default_synonyms():
    """Import standard astronomy synonym sets (UAT, astroJargon, etc.)"""
    conn = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)

    BIBMAN_RAW = 'https://raw.githubusercontent.com/pmarcum/BibMan/main/synonyms/'
    sources    = {
        'astroJargon':  BIBMAN_RAW + 'astroJargon.tsv',
        'spectralLines':BIBMAN_RAW + 'spectralLines.tsv',
        'ionization':   BIBMAN_RAW + 'ionization.tsv',
    }
    inserted = 0
    for source_name, url in sources.items():
        try:
            r     = requests.get(url, timeout=30)
            lines = r.text.splitlines()
            for line in lines:
                if line.startswith('#') or '\t' not in line:
                    continue
                parts  = line.split('\t')
                term_a = parts[0].strip()
                term_b = parts[1].strip() if len(parts) > 1 else ''
                if not term_a or not term_b:
                    continue
                a_norm = normalize_for_db(term_a)
                b_norm = normalize_for_db(term_b)
                existing = conn.execute(
                    'SELECT id FROM synonyms WHERE library_id=? '
                    'AND ((term_a_norm=? AND term_b_norm=?) OR (term_a_norm=? AND term_b_norm=?))',
                    (library_id, a_norm, b_norm, b_norm, a_norm)
                ).fetchone()
                if not existing:
                    conn.execute('''
                        INSERT INTO synonyms
                            (id,library_id,term_a,term_b,term_a_norm,term_b_norm,
                             source,confidence,is_suppressed)
                        VALUES (?,?,?,?,?,?,?,?,?)
                    ''', (str(uuid.uuid4()), library_id, term_a, term_b,
                          a_norm, b_norm, source_name, 1.0, 0))
                    inserted += 1
        except Exception as e:
            log.warning(f'Failed to import {source_name}: {e}')

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'inserted': inserted})

# ── Config ────────────────────────────────────────────────────────────────────
@app.route('/api/config')
@gas_auth_required
def get_config():
    ads_token, gemini_key = get_request_tokens()
    return jsonify({
        'library_name':  CONFIG.get('library_name'),
        'has_ads_token':  bool(ads_token),
        'has_gemini_key': bool(gemini_key),
    })

@app.route('/api/config', methods=['PATCH'])
@gas_auth_required
def update_config():
    data = request.json or {}
    # Only persist non-sensitive settings
    if 'library_name' in data:
        CONFIG['library_name'] = data['library_name']
    save_config(CONFIG)
    # API keys are BYOK — never persisted, silently ignored if sent here
    return jsonify({'ok': True})

# ── Bulk re-extraction ────────────────────────────────────────────────────────
@app.route('/api/papers/bulk-reextract', methods=['POST'])
@gas_auth_required
def bulk_reextract():
    data       = request.json or {}
    force_all  = data.get('all', False)
    ads_token, gemini_key = get_request_tokens()
    conn       = get_db_connection()
    # Prefer explicit library from client; fall back to server CONFIG
    explicit_lib = (data.get('library') or '').strip()
    if explicit_lib:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (explicit_lib,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
        library_name = explicit_lib
    else:
        library_id, library_name = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)

    if force_all:
        rows = conn.execute(
            'SELECT id, bibcode FROM papers WHERE library_id=?', (library_id,)
        ).fetchall()
    else:
        rows = conn.execute('''
            SELECT DISTINCT p.id, p.bibcode
            FROM papers p
            WHERE p.library_id=?
              AND (
                p.pdf_extracted != 1
                OR NOT EXISTS (
                    SELECT 1 FROM passages pa
                    WHERE pa.paper_id = p.id
                      AND (pa.x1 != 0 OR pa.y1 != 0 OR pa.x2 != 1 OR pa.y2 != 1)
                )
              )
        ''', (library_id,)).fetchall()

    paper_ids = [(r['id'], r['bibcode']) for r in rows]
    conn.close()

    if not paper_ids:
        return jsonify({'ok': True, 'queued': 0,
                        'message': 'All papers already have spatial data.'})

    def _run():
        ok = fail = 0
        for paper_id, bibcode in paper_ids:
            try:
                conn2 = get_db_connection()
                paper = conn2.execute(
                    'SELECT * FROM papers WHERE id=?', (paper_id,)
                ).fetchone()
                conn2.close()
                if not paper:
                    continue
                pd = dict(paper)
                pd['identifiers'] = []
                content, source_type, source_url, no_free_pdf = fetch_content_for_paper(pd, ads_token)
                if not content:
                    fail += 1
                    continue
                text = extract_text_from_pdf(content) if source_type == 'pdf' \
                       else extract_text_from_html(content)
                if not text:
                    fail += 1
                    continue
                passages = chunk_text(text, paper_id)
                if passages and write_passages_to_db(paper_id, passages, bibcode,
                                                     source_url):
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                log.error(f'Bulk reextract {bibcode}: {e}')
                fail += 1
        log.info(f'Bulk reextract done: {ok} ok, {fail} failed in {library_name}')

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'ok': True, 'queued': len(paper_ids),
                    'message': f'Re-extraction queued for {len(paper_ids)} papers.'})

# ── Import .bib ───────────────────────────────────────────────────────────────
@app.route('/api/papers/import-bib', methods=['POST'])
@gas_auth_required
def import_bib_file():
    """Import papers from a .bib file (JSON body with 'bib_content' field)."""
    data        = request.json or {}
    bib_content = data.get('bib_content', '')
    if not bib_content:
        return err('bib_content required')

    conn = get_db_connection()
    # Prefer explicit library from client; fall back to server CONFIG
    explicit_lib = (data.get('library') or '').strip()
    if explicit_lib:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (explicit_lib,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
    else:
        library_id, _ = get_current_library_id(conn)
    if not library_id:
        conn.close()
        return err('Library not found', 404)

    # Simple bibtex parser
    entries  = re.findall(
        r'@(\w+)\{([^,]+),([^@]+)\}', bib_content, re.DOTALL
    )
    added    = 0
    skipped  = 0

    for pubtype, bibkey, fields_str in entries:
        bibkey = bibkey.strip()
        fields = {}
        for m in re.finditer(r'(\w+)\s*=\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
                             fields_str, re.DOTALL):
            fields[m.group(1).lower()] = m.group(2).strip()

        # Reconstruct bibkey in BibMan format
        bibkey = _make_bibkey(
            fields.get('author', ''),
            fields.get('year', ''),
            fields.get('journal', ''),
            fields.get('volume', ''),
            fields.get('pages', ''),
            pubtype,
            fields.get('booktitle', '')
        ) or bibkey.strip()
        # Handle duplicate bibkey with suffix a, b, c...
        base_key = bibkey
        suffix   = 0
        while conn.execute(
            'SELECT id FROM papers WHERE library_id=? AND bibkey=?',
            (library_id, bibkey)
        ).fetchone():
            suffix += 1
            if suffix > 25:
                skipped += 1
                break
            bibkey = f'{base_key}{chr(96+suffix)}'
        if suffix > 25:
            continue

        paper_id = str(uuid.uuid4())
        conn.execute('''
            INSERT INTO papers
                (id,library_id,bibkey,title,authors,year,journal,
                 volume,pages,pubtype,doi,bibtex,read_status,pdf_extracted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (
            paper_id, library_id, bibkey,
            fields.get('title', ''),
            fields.get('author', ''),
            fields.get('year', ''),
            fields.get('journal', ''),
            fields.get('volume', ''),
            fields.get('pages', ''),
            pubtype,
            fields.get('doi', ''),
            f'@{pubtype}{{{bibkey},{fields_str}}}',
            'unread', 0
        ))

        added += 1
        # Extract arXiv ID from eprint field
        eprint   = fields.get('eprint', '').strip()
        archive  = fields.get('archiveprefix', '').strip().lower()
        arxiv_id = eprint if (archive == 'arxiv'
                              or re.match(r'^\d{4}\.\d{4,5}$', eprint)
                              or re.match(r'^[a-z\-]+/\d+$', eprint)) else ''

        # Extract bibcode — prefer explicit field, fall back to adsurl
        bibcode_f = fields.get('bibcode', '').strip()
        adsurl    = fields.get('adsurl', '').strip()
        if not bibcode_f and adsurl:
            m = re.search(r'/abs/([^/\?#]+)', adsurl)
            if m: bibcode_f = m.group(1)

        # Set pdf_url: arXiv is best recovery source
        # Never store ADS abstract page URLs (adsurl field) as pdf_url
        # articles.adsabs.harvard.edu/pdf/ URLs are real PDFs — those come
        # from pdf_url field in bib entry if present
        existing_pdf_url = fields.get('pdf_url', '').strip()
        if arxiv_id:
            pdf_url_f = f'https://arxiv.org/pdf/{arxiv_id}'
        elif existing_pdf_url and 'adsabs.harvard.edu/pdf/' in existing_pdf_url:
            pdf_url_f = existing_pdf_url  # real PDF URL, keep it
        else:
            pdf_url_f = ''  # don't store abstract page URLs

        # Update bibcode and pdf_url now that we have better values
        conn.execute(
            'UPDATE papers SET bibcode=?, pdf_url=? WHERE id=?',
            (bibcode_f, pdf_url_f, paper_id)
        )

        # Queue background ingest if there is any identifier to work with
        doi_f = fields.get('doi', '').strip()
        ads_token, gemini_key = get_request_tokens()

        # Build identifiers list — this is what fetch_content_for_paper uses
        # to find the arXiv PDF. Must include arXiv: prefix if present.
        identifiers = []
        if arxiv_id:
            identifiers.append(f'arXiv:{arxiv_id}')
        if doi_f:
            identifiers.append(doi_f)

        # Query ADS for bibcode AND full identifier list (gets arXiv ID if exists)
        # Request fl=bibcode,identifier in one call — more efficient than two calls
        if doi_f and ads_token and not arxiv_id:
            try:
                ads_resp = requests.get(
                    'https://api.adsabs.harvard.edu/v1/search/query',
                    params={'q': f'doi:{doi_f}',
                            'fl': 'bibcode,identifier',
                            'rows': 1},
                    headers={'Authorization': f'Bearer {ads_token}'},
                    timeout=10
                )
                docs = ads_resp.json().get('response', {}).get('docs', [])
                if docs:
                    resolved_bibcode = docs[0].get('bibcode', '')
                    if resolved_bibcode and not bibcode_f:
                        bibcode_f = resolved_bibcode
                        conn.execute('UPDATE papers SET bibcode=? WHERE id=?',
                                     (bibcode_f, paper_id))
                        log.info(f'Resolved bibcode {bibcode_f} from doi {doi_f}')
                    # Extract arXiv ID from ADS identifier list
                    for ident in (docs[0].get('identifier') or []):
                        if ident.lower().startswith('arxiv:'):
                            identifiers.append(ident)
                            # Also set pdf_url so fetch_content_for_paper
                            # can find it even without identifiers
                            arxiv_bare = ident.split(':', 1)[1].strip()
                            conn.execute(
                                'UPDATE papers SET pdf_url=? WHERE id=?',
                                (f'https://arxiv.org/pdf/{arxiv_bare}', paper_id)
                            )
                            log.info(f'Found arXiv ID {arxiv_bare} via ADS for doi={doi_f}')
                            break
            except Exception as e:
                log.warning(f'ADS lookup failed for doi={doi_f}: {e}')
        elif bibcode_f and ads_token and not arxiv_id:
            # Have bibcode but no DOI and no arXiv — still try to get arXiv ID
            try:
                ads_resp = requests.get(
                    'https://api.adsabs.harvard.edu/v1/search/query',
                    params={'q': f'bibcode:{bibcode_f}',
                            'fl': 'bibcode,identifier',
                            'rows': 1},
                    headers={'Authorization': f'Bearer {ads_token}'},
                    timeout=10
                )
                docs = ads_resp.json().get('response', {}).get('docs', [])
                if docs:
                    for ident in (docs[0].get('identifier') or []):
                        if ident.lower().startswith('arxiv:'):
                            identifiers.append(ident)
                            arxiv_bare = ident.split(':', 1)[1].strip()
                            conn.execute(
                                'UPDATE papers SET pdf_url=? WHERE id=?',
                                (f'https://arxiv.org/pdf/{arxiv_bare}', paper_id)
                            )
                            log.info(f'Found arXiv ID {arxiv_bare} via ADS for bibcode={bibcode_f}')
                            break
            except Exception as e:
                log.warning(f'ADS identifier lookup failed for bibcode={bibcode_f}: {e}')

        if bibcode_f or doi_f or arxiv_id or identifiers:
            threading.Thread(
                target=ingest_paper_background,
                args=(paper_id, bibcode_f, identifiers, ads_token, gemini_key),
                daemon=True
            ).start()

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'added': added, 'skipped': skipped})

# ── BibTeX export (for gooTeX integration) ───────────────────────────────────

@app.route('/api/export/bib', methods=['POST'])
@export_auth_required
def export_bib():
    """
    Given a list of bibkeys, return matching BibTeX entries as a single string.
    Used by gooTeX to build a .bib file from cited papers.

    Request JSON:
        {
            "bibkeys": ["smith+2024apj123", "jones+2019mnras234"],
            "library": "Extragalactic"   # optional, searches all libraries if omitted
        }

    Response JSON:
        {
            "bibtex":   "@ARTICLE{...}\n\n@ARTICLE{...}",
            "found":    12,
            "missing":  ["unknownkey+2020"],
            "total_requested": 13
        }
    """
    data      = request.json or {}
    bibkeys   = data.get('bibkeys', [])
    library   = (data.get('library') or '').strip()

    if not bibkeys:
        return err('bibkeys list required')

    conn = get_db_connection()

    # Optionally filter by library
    if library:
        lib_row = conn.execute('SELECT id FROM libraries WHERE name=?', (library,)).fetchone()
        library_id = lib_row['id'] if lib_row else None
    else:
        library_id = None

    # Fetch papers matching the requested bibkeys
    ph = ','.join('?' * len(bibkeys))
    if library_id:
        rows = conn.execute(
            f'SELECT bibkey, bibtex, pubtype, title, authors, year, journal, '
            f'volume, pages, doi, bibcode FROM papers '
            f'WHERE bibkey IN ({ph}) AND library_id=?',
            bibkeys + [library_id]
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT bibkey, bibtex, pubtype, title, authors, year, journal, '
            f'volume, pages, doi, bibcode FROM papers '
            f'WHERE bibkey IN ({ph})',
            bibkeys
        ).fetchall()
    conn.close()

    found_keys = set()
    entries    = []

    for r in rows:
        found_keys.add(r['bibkey'])
        if r['bibtex'] and r['bibtex'].strip():
            # Use stored BibTeX if available
            entries.append(r['bibtex'].strip())
        else:
            # Generate BibTeX from fields
            pubtype = r['pubtype'] or 'article'
            bibkey  = r['bibkey']
            lines   = [f'@{pubtype}{{{bibkey},']
            if r['authors']: lines.append(f'  author  = {{{r["authors"]}}},')
            if r['title']:   lines.append(f'  title   = {{{r["title"]}}},')
            if r['year']:    lines.append(f'  year    = {{{r["year"]}}},')
            if r['journal']: lines.append(f'  journal = {{{r["journal"]}}},')
            if r['volume']:  lines.append(f'  volume  = {{{r["volume"]}}},')
            if r['pages']:   lines.append(f'  pages   = {{{r["pages"]}}},')
            if r['doi']:     lines.append(f'  doi     = {{{r["doi"]}}},')
            if r['bibcode']: lines.append(
                f'  adsurl  = {{https://ui.adsabs.harvard.edu/abs/{r["bibcode"]}}},')
            lines.append('}')
            entries.append('\n'.join(lines))

    missing = [k for k in bibkeys if k not in found_keys]

    return jsonify({
        'bibtex':          '\n\n'.join(entries),
        'found':           len(found_keys),
        'missing':         missing,
        'total_requested': len(bibkeys),
    })


# ── Annotated papers ──────────────────────────────────────────────────────────
@app.route('/api/my-annotated-papers')
@gas_auth_required
def get_my_annotated_papers():
    user_id = get_user_id()
    conn    = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    rows = conn.execute('''
        SELECT DISTINCT pp.id, pp.bibkey, pp.title, pp.authors, pp.year
        FROM annotations a
        JOIN papers pp ON pp.id = a.paper_id
        WHERE pp.library_id=? AND a.username=?
        ORDER BY pp.bibkey
    ''', (library_id, user_id)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))

# ── Status ────────────────────────────────────────────────────────────────────
@app.route('/api/status')
@gas_auth_required
def api_status():
    return jsonify({
        'db_exists':  DB_PATH.exists(),
        'library':    CONFIG.get('library_name'),
        'vec_enabled': VEC_AVAILABLE,
    })

# ── Annotation embedding backfill ─────────────────────────────────────────────

@app.route('/api/annotations/missing-embeddings', methods=['GET'])
@gas_auth_required
def get_annotations_missing_embeddings():
    """Return list of annotations that have text but no embedding."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT a.id,
               COALESCE(a.user_note, a.quote, '') as text
        FROM annotations a
        WHERE COALESCE(a.user_note, a.quote, '') != ''
          AND NOT EXISTS (
              SELECT 1 FROM vec_annotations_rowids vr WHERE vr.id = a.id
          )
        ORDER BY a.created_at
    ''').fetchall()
    conn.close()
    return jsonify([{'id': r['id'], 'text': r['text']} for r in rows])


@app.route('/api/papers/<paper_id>/backfill-embeddings', methods=['POST'])
@gas_auth_required
def backfill_embeddings(paper_id):
    """
    For a paper that already has passages but is missing embeddings/synonyms,
    generate and store both without re-fetching or re-extracting the PDF.
    """
    _, gemini_key = get_request_tokens()
    if not gemini_key:
        return err('Gemini key required')

    conn = get_db_connection()
    paper = conn.execute('SELECT id, library_id, bibcode FROM papers WHERE id=?',
                         (paper_id,)).fetchone()
    if not paper:
        conn.close()
        return err('Paper not found', 404)

    # Fetch existing passages
    rows = conn.execute(
        'SELECT id, text FROM passages WHERE paper_id=? ORDER BY page_number, passage_index',
        (paper_id,)
    ).fetchall()
    if not rows:
        conn.close()
        return jsonify({'ok': False, 'message': 'No passages found for this paper'})

    passages = [{'id': r['id'], 'text': r['text'] or ''} for r in rows]

    # Check which passages already have embeddings
    existing_ids = set()
    try:
        ex_rows = conn.execute(
            'SELECT id FROM vec_passages_rowids'
        ).fetchall()
        existing_ids = {r['id'] for r in ex_rows}
    except Exception:
        pass

    to_embed = [p for p in passages if p['id'] not in existing_ids]
    embedded_count = 0

    if to_embed:
        embedded = embed_passages(to_embed, gemini_key, get_request_models()[0])
        if embedded:
            try:
                conn.executemany(
                    'INSERT OR IGNORE INTO vec_passages (passage_id, embedding) VALUES (?,?)',
                    embedded
                )
                conn.commit()
                embedded_count = len(embedded)
            except Exception as e:
                log.warning(f'backfill_embeddings vec insert failed: {e}')

    # Generate synonyms
    syn_count = 0
    try:
        syn_count = suggest_synonyms_for_paper(
            paper_id, paper['library_id'], conn, gemini_key
        )
    except Exception as e:
        log.warning(f'backfill_embeddings synonym failed: {e}')

    conn.close()
    log.info(f'backfill_embeddings: {paper_id} — {embedded_count} embeddings, {syn_count} synonyms')
    return jsonify({
        'ok':        True,
        'paper_id':  paper_id,
        'embedded':  embedded_count,
        'synonyms':  syn_count,
        'skipped':   len(passages) - len(to_embed),
    })


@app.route('/api/backfill/annotations', methods=['GET'])
@gas_auth_required
def get_annotation_backfill_list():
    """Return annotations missing embeddings."""
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT a.id, a.paper_id, a.user_note, a.quote,
               p.bibkey
        FROM annotations a
        JOIN papers p ON p.id = a.paper_id
        WHERE a.id NOT IN (SELECT annotation_id FROM vec_annotations_rowids)
          AND (a.user_note IS NOT NULL OR a.quote IS NOT NULL)
        ORDER BY p.bibkey
    ''').fetchall()
    conn.close()
    result = []
    for r in rows:
        text = (r['user_note'] or r['quote'] or '').strip()
        if text:
            result.append({
                'id':     r['id'],
                'bibkey': r['bibkey'],
                'text':   text,
            })
    return jsonify(result)


@app.route('/api/annotations/<ann_id>/embed', methods=['POST'])
@gas_auth_required
def embed_annotation_endpoint(ann_id):
    """Generate and store embedding for a single annotation."""
    _, gemini_key = get_request_tokens()
    if not gemini_key:
        return err('Gemini key required')

    conn = get_db_connection()
    row = conn.execute(
        'SELECT a.id, a.paper_id, a.user_note, a.quote FROM annotations a WHERE a.id=?',
        (ann_id,)
    ).fetchone()
    if not row:
        conn.close()
        return err('Annotation not found', 404)

    text = (row['user_note'] or row['quote'] or '').strip()
    if not text:
        conn.close()
        return jsonify({'ok': True, 'skipped': True, 'reason': 'no text'})

    # FTS
    try:
        conn.execute('DELETE FROM annotations_fts WHERE annotation_id=?', (ann_id,))
        conn.execute(
            'INSERT INTO annotations_fts (user_note, annotation_id) VALUES (?,?)',
            (text, ann_id)
        )
        conn.commit()
    except Exception as e:
        log.warning(f'embed_annotation_endpoint FTS failed: {e}')

    # Vector embedding
    if VEC_AVAILABLE:
        vec = embed_query(text, gemini_key)
        if vec:
            try:
                conn.execute('DELETE FROM vec_annotations WHERE annotation_id=?', (ann_id,))
                conn.execute(
                    'INSERT INTO vec_annotations (annotation_id, embedding) VALUES (?,?)',
                    (ann_id, vec)
                )
                conn.commit()
            except Exception as e:
                log.warning(f'embed_annotation_endpoint vec failed: {e}')

    conn.close()
    return jsonify({'ok': True, 'skipped': False})


@app.route('/api/backfill/list', methods=['GET'])
@gas_auth_required
def get_backfill_list():
    """Return list of paper_ids that have passages but missing embeddings."""
    conn = get_db_connection()
    library_id, _ = get_current_library_id(conn)
    # Use a faster approach: count passages vs embeddings per paper
    rows = conn.execute('''
        SELECT p.id, p.bibkey,
               COUNT(pa.id) as passage_count,
               COUNT(vr.id) as embed_count
        FROM papers p
        JOIN passages pa ON pa.paper_id = p.id
        LEFT JOIN vec_passages_rowids vr ON vr.id = pa.id
        WHERE p.library_id = ?
        GROUP BY p.id, p.bibkey
        HAVING COUNT(pa.id) > COUNT(vr.id)
        ORDER BY p.bibkey
    ''', (library_id,)).fetchall()
    conn.close()
    return jsonify([{'id': r['id'], 'bibkey': r['bibkey'], 'missing': r['passage_count'] - r['embed_count']} for r in rows])



@app.route('/api/mentions', methods=['POST'])
@gas_auth_required
def create_mention():
    data          = request.json or {}
    paper_id      = data.get('paper_id', '').strip()
    annotation_id = (data.get('annotation_id') or '').strip() or None
    mentioned_user= data.get('mentioned_user', '').strip()
    note          = data.get('note', '').strip()
    if not paper_id or not mentioned_user:
        return err('paper_id and mentioned_user required')

    mentioned_by = get_user_id()
    conn = get_db_connection()

    # Expand @team to all team members
    if mentioned_user == 'team':
        members = [r['username'] for r in
                   conn.execute('SELECT username FROM team_members').fetchall()]
    else:
        members = [mentioned_user]

    for user in members:
        conn.execute('''
            INSERT INTO mentions (id, paper_id, annotation_id, mentioned_by, mentioned_user, note)
            VALUES (?,?,?,?,?,?)
        ''', (str(uuid.uuid4()), paper_id, annotation_id, mentioned_by, user, note))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'count': len(members)})


@app.route('/api/mentions/unread', methods=['GET'])
@gas_auth_required
def get_unread_mentions():
    username = get_user_id()
    conn = get_db_connection()
    rows = conn.execute('''
        SELECT m.id, m.paper_id, m.annotation_id, m.mentioned_by,
               m.note, m.created_at,
               p.bibkey, p.title
        FROM mentions m
        JOIN papers p ON p.id = m.paper_id
        WHERE m.mentioned_user = ? AND m.seen = 0
        ORDER BY m.created_at DESC
    ''', (username,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/mentions/<mention_id>/seen', methods=['PATCH'])
@gas_auth_required
def mark_mention_seen(mention_id):
    conn = get_db_connection()
    conn.execute('UPDATE mentions SET seen=1 WHERE id=?', (mention_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/mentions/seen-all', methods=['PATCH'])
@gas_auth_required
def mark_all_mentions_seen():
    username = get_user_id()
    conn = get_db_connection()
    conn.execute('UPDATE mentions SET seen=1 WHERE mentioned_user=?', (username,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/mentions/count', methods=['GET'])
@gas_auth_required
def get_mention_count():
    username = get_user_id()
    conn = get_db_connection()
    count = conn.execute(
        'SELECT COUNT(*) FROM mentions WHERE mentioned_user=? AND seen=0',
        (username,)
    ).fetchone()[0]
    conn.close()
    return jsonify({'count': count})


# ── User tags (post-it notes) ─────────────────────────────────────────────────

@app.route('/api/tags/labels', methods=['GET'])
@gas_auth_required
def get_tag_labels():
    """Get all tag labels. With ?all=1 returns everyone's, otherwise just current user's."""
    user_id  = get_user_id()
    conn     = get_db_connection()
    show_all = request.args.get('all', '0') == '1'
    if show_all:
        rows = conn.execute('''
            SELECT l.id, l.user_id, l.label, l.color, l.created_at,
                   COUNT(pt.id) as usage_count
            FROM user_tag_labels l
            LEFT JOIN paper_tags pt ON pt.label_id = l.id
            GROUP BY l.id ORDER BY l.user_id, l.label
        ''').fetchall()
    else:
        rows = conn.execute('''
            SELECT l.id, l.user_id, l.label, l.color, l.created_at,
                   COUNT(pt.id) as usage_count
            FROM user_tag_labels l
            LEFT JOIN paper_tags pt ON pt.label_id = l.id
            WHERE l.user_id = ?
            GROUP BY l.id ORDER BY l.label
        ''', (user_id,)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/tags/labels', methods=['POST'])
@gas_auth_required
def create_tag_label():
    """Create a new tag label for the current user."""
    user_id = get_user_id()
    data    = request.json or {}
    label   = (data.get('label') or '').strip()
    color   = (data.get('color') or '#f59e0b').strip()
    if not label:
        return err('label required')
    conn = get_db_connection()
    # Check max 8 labels per user
    count = conn.execute('SELECT COUNT(*) FROM user_tag_labels WHERE user_id=?',
                         (user_id,)).fetchone()[0]
    if count >= 8:
        conn.close()
        return err('Maximum 8 labels per user')
    label_id = str(uuid.uuid4())
    try:
        conn.execute('INSERT INTO user_tag_labels (id,user_id,label,color) VALUES (?,?,?,?)',
                     (label_id, user_id, label, color))
        conn.commit()
    except Exception as e:
        conn.close()
        return err(f'Label already exists: {label}')
    conn.close()
    return jsonify({'ok': True, 'id': label_id, 'label': label, 'color': color})


@app.route('/api/tags/labels/<label_id>', methods=['PATCH'])
@gas_auth_required
def update_tag_label(label_id):
    """Update label name or color."""
    user_id = get_user_id()
    data    = request.json or {}
    conn    = get_db_connection()
    label   = conn.execute('SELECT * FROM user_tag_labels WHERE id=? AND user_id=?',
                           (label_id, user_id)).fetchone()
    if not label:
        conn.close()
        return err('Label not found', 404)
    new_label = (data.get('label') or label['label']).strip()
    new_color = (data.get('color') or label['color']).strip()
    conn.execute('UPDATE user_tag_labels SET label=?, color=? WHERE id=?',
                 (new_label, new_color, label_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/tags/labels/<label_id>', methods=['DELETE'])
@gas_auth_required
def delete_tag_label(label_id):
    """Delete a label and all its paper_tags."""
    user_id = get_user_id()
    conn    = get_db_connection()
    conn.execute('DELETE FROM paper_tags WHERE label_id=? AND user_id=?', (label_id, user_id))
    conn.execute('DELETE FROM user_tag_labels WHERE id=? AND user_id=?', (label_id, user_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/papers/<paper_id>/tags', methods=['GET'])
@gas_auth_required
def get_paper_tags(paper_id):
    """Get all tags for a paper. With ?all=1 returns everyone's."""
    user_id  = get_user_id()
    show_all = request.args.get('all', '0') == '1'
    conn     = get_db_connection()
    if show_all:
        rows = conn.execute('''
            SELECT pt.id, pt.user_id, pt.label_id, pt.annotation_id,
                   l.label, l.color, pt.created_at
            FROM paper_tags pt
            JOIN user_tag_labels l ON l.id = pt.label_id
            WHERE pt.paper_id = ?
            ORDER BY pt.annotation_id NULLS FIRST, pt.user_id, l.label
        ''', (paper_id,)).fetchall()
    else:
        rows = conn.execute('''
            SELECT pt.id, pt.user_id, pt.label_id, pt.annotation_id,
                   l.label, l.color, pt.created_at
            FROM paper_tags pt
            JOIN user_tag_labels l ON l.id = pt.label_id
            WHERE pt.paper_id = ? AND pt.user_id = ?
            ORDER BY pt.annotation_id NULLS FIRST, l.label
        ''', (paper_id, user_id)).fetchall()
    conn.close()
    return jsonify(rows_to_list(rows))


@app.route('/api/papers/<paper_id>/tags', methods=['POST'])
@gas_auth_required
def add_paper_tag(paper_id):
    """Apply a tag label to a paper or a specific annotation within it."""
    user_id       = get_user_id()
    data          = request.json or {}
    label_id      = (data.get('label_id') or '').strip()
    annotation_id = (data.get('annotation_id') or None)
    if not label_id:
        return err('label_id required')
    conn = get_db_connection()
    label = conn.execute('SELECT * FROM user_tag_labels WHERE id=? AND user_id=?',
                         (label_id, user_id)).fetchone()
    if not label:
        conn.close()
        return err('Label not found', 404)
    tag_id = str(uuid.uuid4())
    try:
        conn.execute(
            'INSERT OR IGNORE INTO paper_tags (id,paper_id,user_id,label_id,annotation_id) VALUES (?,?,?,?,?)',
            (tag_id, paper_id, user_id, label_id, annotation_id)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return err(str(e))
    conn.close()
    return jsonify({'ok': True, 'tag_id': tag_id})


@app.route('/api/papers/<paper_id>/tags/<label_id>', methods=['DELETE'])
@gas_auth_required
def remove_paper_tag(paper_id, label_id):
    """Remove a tag from a paper or annotation."""
    user_id       = get_user_id()
    annotation_id = request.args.get('annotation_id') or None
    conn          = get_db_connection()
    if annotation_id:
        conn.execute(
            'DELETE FROM paper_tags WHERE paper_id=? AND label_id=? AND user_id=? AND annotation_id=?',
            (paper_id, label_id, user_id, annotation_id)
        )
    else:
        conn.execute(
            'DELETE FROM paper_tags WHERE paper_id=? AND label_id=? AND user_id=? AND annotation_id IS NULL',
            (paper_id, label_id, user_id)
        )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


@app.route('/api/papers/tagged', methods=['GET'])
@gas_auth_required
def get_tagged_papers():
    """Get paper IDs tagged with specific labels. Used for filtering."""
    user_id   = get_user_id()
    label_ids = request.args.getlist('label_id')
    show_all  = request.args.get('all', '0') == '1'
    if not label_ids:
        return jsonify([])
    conn = get_db_connection()
    ph   = ','.join('?' * len(label_ids))
    if show_all:
        rows = conn.execute(
            f'SELECT DISTINCT paper_id FROM paper_tags WHERE label_id IN ({ph})',
            label_ids
        ).fetchall()
    else:
        rows = conn.execute(
            f'SELECT DISTINCT paper_id FROM paper_tags WHERE label_id IN ({ph}) AND user_id=?',
            label_ids + [user_id]
        ).fetchall()
    conn.close()
    return jsonify([r['paper_id'] for r in rows])


# ── Team members ──────────────────────────────────────────────────────────────

@app.route('/api/team', methods=['GET'])
@gas_auth_required
def get_team():
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT id, username, added_by, created_at FROM team_members ORDER BY username'
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/team', methods=['POST'])
@gas_auth_required
def add_team_member():
    data     = request.json or {}
    username = (data.get('username') or '').strip().lower()
    if not username:
        return err('username required')
    added_by = get_user_id()
    conn = get_db_connection()
    try:
        conn.execute(
            'INSERT INTO team_members (id, username, added_by) VALUES (?,?,?)',
            (str(uuid.uuid4()), username, added_by)
        )
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    except Exception:
        # User already exists - this is fine, return success anyway
        conn.close()
        return jsonify({'ok': True, 'already_exists': True})


@app.route('/api/team/<member_id>', methods=['DELETE'])
@gas_auth_required
def remove_team_member(member_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM team_members WHERE id=?', (member_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})


# ── Startup ───────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    log.info(f'BibMan E2-micro starting on localhost:{PORT}')
    log.info(f'DB: {DB_PATH}')
    log.info(f'DB exists: {DB_PATH.exists()}')
    if not DB_PATH.exists():
        log.warning(f'WARNING: Database not found at {DB_PATH}')
    app.run(host='127.0.0.1', port=PORT, debug=False, threaded=True)
