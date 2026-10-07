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
  * The new index is written to a temporary file and checked (count, key lookups, self-searches) before it
    replaces anything.
  * The current index and its method file are kept as *.prev, so going back is one command (--rollback).
    An existing *.prev is never overwritten unless you pass --replace-prev.
  * It does NOT restart BibMan; it prints the command. The running server keeps the old index until then.

Compression method (how each 768-dim float vector becomes int8), recorded in bibman_768_i8.usearch.method so
the server compresses search queries the same way:
  A  x127, no normalising           (how the April 2026 index was built; also assumed when no method file)
  B  normalise, then x127
  C  scale each vector to its own maximum, then x127   (default; most precise for cosine search)

Usage (as the bibman user, with BibMan's Python; run when nobody is using BibMan or gooTeX):
  sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --dry-run
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py [--method C] [--replace-prev]
  sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --rollback
then: sudo systemctl restart bibman
"""
import os, sys, time, sqlite3, argparse
from pathlib import Path
import numpy as np

DIMS, BATCH = 768, 2000
ap = argparse.ArgumentParser()
ap.add_argument('--method', choices='ABC', default='C')
ap.add_argument('--dry-run', action='store_true')
ap.add_argument('--replace-prev', action='store_true', help='allow overwriting an existing .prev backup')
ap.add_argument('--rollback', action='store_true', help='swap the .prev index (and method) back in, then exit')
args = ap.parse_args()

DB_PATH = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
D = DB_PATH.parent
INDEX, TMP, PREV = D / 'bibman_768_i8.usearch', D / 'bibman_768_i8.usearch.tmp', D / 'bibman_768_i8.usearch.prev'
METHOD, METHOD_PREV = D / 'bibman_768_i8.usearch.method', D / 'bibman_768_i8.usearch.method.prev'
STAMP = D / 'bibman_768.usearch.timestamp'

def log(msg): print(time.strftime('%H:%M:%S'), msg, flush=True)
def method_of(p: Path) -> str: return (p.read_text().strip().upper()[:1] if p.exists() else 'A') or 'A'

def compress(V: np.ndarray, method: str) -> np.ndarray:
    """V: (n, 768) float32 -> (n, 768) int8. Must match quantize_query() in the server."""
    if method == 'A':
        return (V * 127).astype(np.int8)
    if method == 'B':
        V = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-12)
        return np.clip(V * 127, -127, 127).astype(np.int8)
    V = V / np.maximum(np.abs(V).max(axis=1, keepdims=True), 1e-12)
    return np.clip(np.round(V * 127), -127, 127).astype(np.int8)

if args.rollback:
    if not PREV.exists(): sys.exit(f'nothing to roll back to: {PREV} does not exist')
    cur_m, prev_m = method_of(METHOD), method_of(METHOD_PREV)
    INDEX.replace(TMP); PREV.replace(INDEX); TMP.replace(PREV)          # swap current <-> previous
    METHOD.write_text(prev_m + '\n'); METHOD_PREV.write_text(cur_m + '\n')
    log(f'rolled back: {INDEX.name} is now the previous index (method {prev_m}); the newer one is kept as {PREV.name}')
    log('load it with:  sudo systemctl restart bibman'); sys.exit(0)

import sqlite_vec
from usearch.index import Index
t0 = time.time()
con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=60)
con.enable_load_extension(True); sqlite_vec.load(con); con.enable_load_extension(False)
n_keyed = con.execute('SELECT COUNT(*) FROM passages WHERE search_id IS NOT NULL').fetchone()[0]
n_emb   = con.execute('SELECT COUNT(*) FROM vec_passages_rowids').fetchone()[0]
n_nokey = con.execute('SELECT COUNT(*) FROM vec_passages_rowids WHERE id NOT IN '
                      '(SELECT id FROM passages WHERE search_id IS NOT NULL)').fetchone()[0]
log(f'database {DB_PATH}: {n_emb:,} embeddings, {n_keyed:,} passages with a search ID, '
    f'{n_nokey:,} embeddings without one (will be skipped)')
log(f'method {args.method}; new index -> {INDEX.name}; current one (method {method_of(METHOD)}) -> {PREV.name}')
if PREV.exists() and not args.replace_prev:
    sys.exit(f'STOP: {PREV.name} already exists (an earlier backup). Keep it by moving it elsewhere, or pass '
             '--replace-prev to overwrite it. Nothing changed.')
if args.dry_run:
    log('dry run: nothing built, nothing changed'); sys.exit(0)
if n_nokey:
    log(f'note: {n_nokey:,} embedded passages have no search ID and will be missing from the index; '
        'run bibman_backfill_search_ids.py --apply first to include them')

index = Index(ndim=DIMS, dtype='i8', metric='cos', connectivity=16, expansion_add=128, expansion_search=8)
added = skipped = 0; probes = []
cur = con.execute('SELECT passage_id, embedding FROM vec_passages')
while True:
    rows = cur.fetchmany(BATCH)
    if not rows: break
    ids = [r[0] for r in rows]   # look up this batch's search IDs (keeps memory low on a 1 GB machine)
    key_of = dict(con.execute(f'SELECT id, search_id FROM passages WHERE search_id IS NOT NULL AND id IN '
                              f'({",".join("?" * len(ids))})', ids))
    keys, vecs = [], []
    for pid, blob in rows:
        k = key_of.get(pid)
        if k is None or not blob: skipped += 1; continue
        keys.append(k); vecs.append(np.frombuffer(blob, dtype=np.float32)[:DIMS])
    if keys:
        Q = compress(np.stack(vecs).astype(np.float32), args.method)
        index.add(np.array(keys, dtype=np.uint64), Q, threads=1)
        if len(probes) < 30: probes.append((keys[0], Q[0].copy()))
        added += len(keys)
    if added and added % 50000 < BATCH: log(f'  {added:,} added')
con.close()
log(f'built: {added:,} vectors, {skipped:,} skipped')
if added == 0: sys.exit('nothing added; current index left untouched')

index.save(str(TMP)); del index
check = Index.restore(str(TMP), view=True); check.expansion_search = 64
ok_get  = sum(check.get(int(k)) is not None for k, _ in probes)
ok_self = sum(int(check.search(v, 1).keys[0]) == int(k) for k, v in probes)
log(f'check: {check.size:,} vectors; {ok_get}/{len(probes)} sample keys present; '
    f'{ok_self}/{len(probes)} sample passages find themselves first')
if check.size != added or ok_get != len(probes) or ok_self < 0.9 * len(probes):
    del check; TMP.unlink(); sys.exit('check FAILED: current index left untouched')
del check
log(f'saved and checked: {TMP.stat().st_size / 2**20:.0f} MB')

# install: keep the current index and its method as .prev, then switch to the new pair
NEW_M = D / 'bibman_768_i8.usearch.method.new'
NEW_M.write_text(args.method + '\n')
METHOD_PREV.write_text(method_of(METHOD) + '\n')
if INDEX.exists(): INDEX.replace(PREV)
TMP.replace(INDEX)
NEW_M.replace(METHOD)
STAMP.write_text(time.strftime('%a %b %d %H:%M:%S UTC %Y', time.gmtime()))
log(f'installed {INDEX.name} (method {args.method}); previous kept as {PREV.name}; {time.time() - t0:.0f}s total')
log('BibMan still uses the old index until restarted:  sudo systemctl restart bibman')
