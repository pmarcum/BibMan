#!/usr/bin/env python3
"""
BibMan search health check: READ-ONLY. It changes nothing: the database is opened read-only,
the search index is only viewed, and no file is written.

Run on the VM (a minute or two):
    sudo -u bibman /home/bibman/bibman/venv/bin/python ~/bibman_search_check.py

It answers, from your real data:
  1. how many passages lack a search ID, and whether they already have embeddings;
  2. whether the search-ID formula matches every existing ID (so new IDs will be consistent);
  3. which method built the live index (compared vector by vector);
  4. how well each compression method finds true nearest neighbours on a sample of your library;
  5. disk space and memory available for a rebuild.
"""
import os, sys, sqlite3, shutil, struct, time
import numpy as np, sqlite_vec
from usearch.index import Index

DB   = os.environ.get('DB_PATH', '/home/bibman/bibman.db')
IDX  = os.path.join(os.path.dirname(DB), 'bibman_768_i8.usearch')
MASK = 0x7FFFFFFFFFFFFFFF
DIM  = 768
t0   = time.time()

def search_id(passage_uuid): return int(passage_uuid.replace('-', '')[:16], 16) & MASK
def vec(blob): return np.frombuffer(blob, dtype=np.float32)[:DIM].astype(np.float32)
METHODS = {   # how a 768-dim float vector becomes the int8 vector stored in the index
    'A live-style  (x127, no normalising)': lambda v: (v * 127).astype(np.int8),
    'B normalise, then x127':               lambda v: np.clip(v / np.linalg.norm(v) * 127, -127, 127).astype(np.int8),
    'C scale each vector to its maximum':   lambda v: np.clip(np.round(v / np.abs(v).max() * 127), -127, 127).astype(np.int8),
}

con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=30)
con.enable_load_extension(True); sqlite_vec.load(con); con.enable_load_extension(False)
q = lambda sql, *a: con.execute(sql, a).fetchall()

print('== 1. Passages and search IDs')
total, missing = q('SELECT COUNT(*), SUM(search_id IS NULL) FROM passages')[0]
emb_total      = q('SELECT COUNT(*) FROM vec_passages_rowids')[0][0]
missing_emb    = q('SELECT COUNT(*) FROM passages WHERE search_id IS NULL AND id IN (SELECT id FROM vec_passages_rowids)')[0][0]
dups           = q('SELECT COUNT(*) - COUNT(DISTINCT search_id) FROM passages WHERE search_id IS NOT NULL')[0][0]
print(f'passages: {total:,}   without search ID: {missing:,}   of those already embedded: {missing_emb:,}')
print(f'embeddings stored: {emb_total:,}   duplicate search IDs among existing: {dups}')

print('== 2. Search-ID formula check (existing IDs)')
rows = q('SELECT id, search_id FROM passages WHERE search_id IS NOT NULL LIMIT 3000')
rows += q('SELECT id, search_id FROM passages WHERE search_id IS NOT NULL LIMIT 3000 OFFSET 200000')
ok = sum(search_id(i) == s for i, s in rows)
print(f'formula reproduces {ok:,} of {len(rows):,} sampled existing IDs' + ('   -> CONSISTENT' if ok == len(rows) else '   -> MISMATCH, do not backfill'))
new_ids = [search_id(r[0]) for r in q('SELECT id FROM passages WHERE search_id IS NULL')]
clash = 0
for i in range(0, len(new_ids), 500):
    chunk = new_ids[i:i + 500]
    clash += q(f'SELECT COUNT(*) FROM passages WHERE search_id IN ({",".join("?" * len(chunk))})', *chunk)[0][0]
print(f'new IDs that would collide with existing ones: {clash}   (duplicates among new IDs: {len(new_ids) - len(set(new_ids))})')

print('== 3. Live index')
if not os.path.exists(IDX): sys.exit(f'index not found at {IDX}')
ix = Index.restore(IDX, view=True)
print(f'{IDX}: {ix.size:,} vectors, {ix.ndim} dims, {os.path.getsize(IDX) / 2**20:.0f} MB')
sample = q('SELECT p.id FROM passages p WHERE p.search_id IS NOT NULL AND p.id IN (SELECT id FROM vec_passages_rowids) LIMIT 150 OFFSET 1000')
ids = [r[0] for r in sample]
embs = dict(q(f'SELECT passage_id, embedding FROM vec_passages WHERE passage_id IN ({",".join("?" * len(ids))})', *ids))
match = {m: 0 for m in METHODS}; absent = 0; compared = 0
for pid in ids:
    stored = ix.get(search_id(pid))
    if stored is None or (hasattr(stored, 'size') and stored.size == 0): absent += 1; continue
    stored = np.asarray(stored).reshape(-1)[:DIM].astype(np.int16); v = vec(embs[pid]); compared += 1
    for m, f in METHODS.items(): match[m] += int(np.array_equal(f(v).astype(np.int16), stored))
print(f'compared {compared} stored vectors (missing from index: {absent})')
for m, n in match.items(): print(f'  identical to method {m}: {n}/{compared}')
print('== 4. Search quality on a sample of your library (higher = better; 1.00 = perfect)')
blobs = []
for off in (0, 100000, 200000, 300000):
    blobs += [r[0] for r in q('SELECT embedding FROM vec_passages LIMIT 1000 OFFSET ?', off)]
T = np.stack([vec(b) for b in blobs]); Tn = T / np.linalg.norm(T, axis=1, keepdims=True)
rng = np.random.default_rng(1); qi = rng.choice(len(T), 100, replace=False)
truth = {i: set(np.argsort(-(Tn @ Tn[i]))[:10]) for i in qi}
for m, f in METHODS.items():
    sub = Index(ndim=DIM, dtype='i8', metric='cos', connectivity=16, expansion_add=128)
    sub.add(np.arange(len(T)), np.stack([f(v) for v in T])); sub.expansion_search = 8   # same as the server
    r_float = np.mean([len(set(sub.search(T[i], 10).keys.tolist()) & truth[i]) / 10 for i in qi])
    r_match = np.mean([len(set(sub.search(f(T[i]), 10).keys.tolist()) & truth[i]) / 10 for i in qi])
    sims    = [1 - float(sub.search(T[i], 10).distances[9]) for i in qi]
    print(f'  {m}: recall@10 {r_float:.2f} (query as sent today) / {r_match:.2f} (query compressed the same way); '
          f'10th-best similarity median {np.median(sims):.2f}')
selfhit = 0; passing = []
for pid in ids[:100]:
    res = ix.search(vec(embs[pid]), 50)
    keys = res.keys.tolist(); selfhit += int(bool(keys) and keys[0] == search_id(pid))
    passing.append(sum(1 - float(d) >= 0.75 for d in res.distances))
print(f'  live index: a passage finds itself first in {selfhit}/100 searches; '
      f'results passing the 0.75 similarity cut (of 50): median {int(np.median(passing))}')

print('== 5. Room for a rebuild')
du = shutil.disk_usage(os.path.dirname(DB)); mem = dict(l.split(':', 1) for l in open('/proc/meminfo'))
kb = lambda k: int(mem[k].split()[0]) // 1024
print(f'disk free: {du.free / 2**30:.1f} GB   memory available: {kb("MemAvailable")} MB   swap free: {kb("SwapFree")} of {kb("SwapTotal")} MB')
print(f'== done in {time.time() - t0:.0f}s, nothing was changed')
