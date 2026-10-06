#!/usr/bin/env python3
"""
BibMan semantic-search index rebuild
=====================================
Rebuilds the USearch index from the embeddings already stored in the database (no Gemini calls).

Constraints (e2-micro, 1 GB RAM):
  * 768 dimensions (the first 768 of Gemini's 3072, which Gemini embeddings are designed to allow), int8.
  * Keys are passages.search_id. Passages without one are skipped: run bibman_backfill_search_ids.py first.

Safe by design:
  * The database is opened READ-ONLY.
  * The new index is written to a temporary file and checked before it replaces anything.
  * The current index is kept as bibman_768_i8.usearch.prev, so going back is one rename.
  * It does NOT restart BibMan; it prints the command. The running server keeps the old index until then.

Compression method (how each 768-dim float vector becomes int8), recorded in bibman_768_i8.usearch.method so
the server compresses search queries the same way:
  A  x127, no normalising           (how the April 2026 index was built)
  B  normalise, then x127
  C  scale each vector to its own maximum, then x127   (default; most precise for cosine search)

Usage (as the bibman user, with BibMan's Python; run when nobody is using BibMan or gooTeX):
  nice -n 19 /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --dry-run
  nice -n 19 /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py [--method C]
"""
import os, sys, time, sqlite3, argparse
from pathlib import Path
import numpy as np, sqlite_vec
from usearch.index import Index

DIMS   = 768
BATCH  = 2000
ap = argparse.ArgumentParser()
ap.add_argument('--method', choices='ABC', default='C')
ap.add_argument('--dry-run', action='store_true')
args = ap.parse_args()

DB_PATH = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
INDEX   = DB_PATH.parent / 'bibman_768_i8.usearch'          # where the server loads it from
TMP     = DB_PATH.parent / 'bibman_768_i8.usearch.tmp'
PREV    = DB_PATH.parent / 'bibman_768_i8.usearch.prev'
METHOD  = DB_PATH.parent / 'bibman_768_i8.usearch.method'
STAMP   = DB_PATH.parent / 'bibman_768.usearch.timestamp'

def compress(V: np.ndarray, method: str) -> np.ndarray:
    """V: (n, 768) float32 -> (n, 768) int8. Must match quantize_query() in the server."""
    if method == 'A':
        return (V * 127).astype(np.int8)
    if method == 'B':
        V = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-12)
        return np.clip(V * 127, -127, 127).astype(np.int8)
    V = V / np.maximum(np.abs(V).max(axis=1, keepdims=True), 1e-12)
    return np.clip(np.round(V * 127), -127, 127).astype(np.int8)

def log(msg): print(time.strftime('%H:%M:%S'), msg, flush=True)

t0 = time.time()
con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=60)
con.enable_load_extension(True); sqlite_vec.load(con); con.enable_load_extension(False)
n_keyed = con.execute('SELECT COUNT(*) FROM passages WHERE search_id IS NOT NULL').fetchone()[0]
n_emb   = con.execute('SELECT COUNT(*) FROM vec_passages_rowids').fetchone()[0]
n_nokey = con.execute('SELECT COUNT(*) FROM vec_passages_rowids WHERE id NOT IN (SELECT id FROM passages WHERE search_id IS NOT NULL)').fetchone()[0]
log(f'database {DB_PATH}: {n_emb:,} embeddings, {n_keyed:,} passages with a search ID, '
    f'{n_nokey:,} embeddings without one (will be skipped)')
log(f'method {args.method}; index will be written to {INDEX} (current one kept as {PREV.name})')
if args.dry_run:
    log('dry run: nothing built, nothing changed'); sys.exit(0)
if n_nokey:
    log(f'note: {n_nokey:,} embedded passages have no search ID; run bibman_backfill_search_ids.py --apply first '
        'if you want them included')

index = Index(ndim=DIMS, dtype='i8', metric='cos', connectivity=16, expansion_add=128, expansion_search=8)
added = 0; skipped = 0
cur = con.execute('SELECT passage_id, embedding FROM vec_passages')
while True:
    rows = cur.fetchmany(BATCH)
    if not rows: break
    # look up this batch's search IDs (keeps memory low on a 1 GB machine)
    ids = [r[0] for r in rows]
    key_of = dict(con.execute(f'SELECT id, search_id FROM passages WHERE search_id IS NOT NULL AND id IN ({",".join("?" * len(ids))})', ids))
    keys, vecs = [], []
    for pid, blob in rows:
        k = key_of.get(pid)
        if k is None or not blob: skipped += 1; continue
        keys.append(k); vecs.append(np.frombuffer(blob, dtype=np.float32)[:DIMS])
    if keys:
        index.add(np.array(keys, dtype=np.uint64), compress(np.stack(vecs).astype(np.float32), args.method))
        added += len(keys)
    if added and added % 50000 < BATCH: log(f'  {added:,} added')
con.close()
log(f'built: {added:,} vectors, {skipped:,} skipped')
if added == 0: sys.exit('nothing added; current index left untouched')

index.save(str(TMP)); del index
check = Index.restore(str(TMP), view=True)
if check.size != added:
    TMP.unlink(); sys.exit(f'check failed ({check.size} != {added}); current index left untouched')
del check
log(f'saved and checked: {TMP.stat().st_size / 2**20:.0f} MB')

if INDEX.exists(): INDEX.replace(PREV)   # keep one previous index
TMP.replace(INDEX)
METHOD.write_text(args.method + '\n')
STAMP.write_text(time.strftime('%a %b %d %H:%M:%S UTC %Y', time.gmtime()))
log(f'installed {INDEX.name} (previous kept as {PREV.name}) in {time.time() - t0:.0f}s')
log('BibMan still uses the old index until restarted:  sudo systemctl restart bibman')
