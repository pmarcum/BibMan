#!/usr/bin/env python3
"""
BibMan semantic-search index rebuild (one index per library)
============================================================
Rebuilds the USearch indexes from the embeddings already stored in the database (no Gemini calls). Each library
gets its own index file, so meaning-based search only ever looks at the current library's passages.

Files, next to the database (named by the library's ID, so renaming a library changes nothing):
  bibman_768_i8.lib-<library id>.usearch        the library's index
  bibman_768_i8.lib-<library id>.usearch.prev   its previous version (kept by a rebuild, used by --rollback)
  bibman_768_i8.libraries.json                  list of the indexes: library, file, vectors, method, build time
The old shared index (bibman_768_i8.usearch) is not touched; the server stops using it once the per-library
indexes are in place.

Constraints (e2-micro, 1 GB RAM):
  * 768 dimensions (the first 768 of Gemini's 3072, which Gemini embeddings are designed to allow), int8.
  * Keys are passages.search_id. Passages without one are skipped: run bibman_backfill_search_ids.py first.
  * Libraries are built one at a time, so peak memory is set by the largest library (about 420 MB for 390,000
    passages), the same as the old shared index.
  * Passages are added in a random order, shuffled across the whole library (fixed seed, so the same data gives the
    same index). Added paper by paper, the index finds passages noticeably less reliably. The shuffle goes through
    temporary files next to the database (about 300 MB for 390,000 passages), removed afterwards.

Safe by design:
  * The database is opened READ-ONLY.
  * Each new index is written to a temporary file and checked before it replaces anything: it must hold every passage,
    and of 300 passages chosen at random across the library, each must be present and at least 97% must come back
    within the first 10 when searched with their own meaning (at the server's search settings). If the check fails,
    the library keeps its current index, and the new one is kept as .failed; --recheck --library NAME checks it again
    and installs it if it passes, so a rebuild is never lost to a check that needed adjusting.
  * Each library's current index is kept as its .prev, so going back is one command (--rollback --library NAME).
    An existing .prev is never overwritten unless you pass --replace-prev. This is checked for every library
    before anything is built.
  * It does NOT restart BibMan; it prints the command. The running server keeps the old indexes until then.

Compression method (how each 768-dim float vector becomes int8), recorded per library in the list file so the
server compresses search queries the same way:
  A  x127, no normalising           (how the April 2026 index was built)
  B  normalise, then x127
  C  scale each vector to its own maximum, then x127   (default; most precise for cosine search)

Usage (as the bibman user, with BibMan's Python; a full rebuild takes hours on an e2-micro, so run it when nobody
is using BibMan or gooTeX; a small library takes seconds):
  sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --dry-run
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py                 # all
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --library Satellites
  sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --rollback --library Satellites
  sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_rebuild_usearch.py --recheck --library Extragalactic
  (add --replace-prev once you are happy with the current indexes; add --method A/B/C to choose compression)
then: sudo systemctl restart bibman
"""
import os, sys, json, time, sqlite3, argparse
from pathlib import Path
import numpy as np

DIMS, BATCH = 768, 2000
ap = argparse.ArgumentParser()
ap.add_argument('--library', action='append', default=[], metavar='NAME', help='only this library (repeatable)')
ap.add_argument('--method', choices='ABC', default='C')
ap.add_argument('--dry-run', action='store_true')
ap.add_argument('--replace-prev', action='store_true', help='allow overwriting existing .prev backups')
ap.add_argument('--rollback', action='store_true', help="swap a library's .prev index back in (needs --library)")
ap.add_argument('--recheck', action='store_true', help="check a library's kept .failed index again and install it if it passes")
args = ap.parse_args()

DB_PATH = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
D = DB_PATH.parent
MANIFEST = D / 'bibman_768_i8.libraries.json'
def index_path(lib_id: str) -> Path: return D / f'bibman_768_i8.lib-{lib_id}.usearch'
def suffixed(p: Path, s: str) -> Path: return p.with_name(p.name + s)
def log(msg): print(time.strftime('%H:%M:%S'), msg, flush=True)
def now_utc(): return time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())

def read_manifest() -> dict:
    if not MANIFEST.exists(): return {'libraries': {}}
    m = json.loads(MANIFEST.read_text())
    m.setdefault('libraries', {})
    return m

def write_manifest(m: dict):  # write a temporary file, then replace, so the list is never half-written
    tmp = suffixed(MANIFEST, '.tmp')
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True) + '\n')
    tmp.replace(MANIFEST)

def compress(V: np.ndarray, method: str) -> np.ndarray:
    """V: (n, 768) float32 -> (n, 768) int8. Must match quantize_query() in the server."""
    if method == 'A':
        return (V * 127).astype(np.int8)
    if method == 'B':
        V = V / np.maximum(np.linalg.norm(V, axis=1, keepdims=True), 1e-12)
        return np.clip(V * 127, -127, 127).astype(np.int8)
    V = V / np.maximum(np.abs(V).max(axis=1, keepdims=True), 1e-12)
    return np.clip(np.round(V * 127), -127, 127).astype(np.int8)

con = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, timeout=60)
libs = dict(con.execute('SELECT name, id FROM libraries ORDER BY name'))
unknown = [n for n in args.library if n not in libs]
if unknown: sys.exit(f'STOP: library not found: {", ".join(unknown)} (libraries: {", ".join(libs)}). Nothing changed.')
chosen = args.library or list(libs)

if args.rollback:
    if len(args.library) != 1: sys.exit('--rollback needs exactly one --library NAME')
    name = args.library[0]; lib_id = libs[name]; idx = index_path(lib_id); prev = suffixed(idx, '.prev')
    if not prev.exists(): sys.exit(f'nothing to roll back to: {prev.name} does not exist')
    m = read_manifest(); entry = m['libraries'].get(lib_id) or {}
    if not entry.get('prev'): sys.exit(f'STOP: the list file has no record of {prev.name}; nothing changed')
    tmp = suffixed(idx, '.swap')
    if idx.exists(): idx.replace(tmp)
    prev.replace(idx)
    if tmp.exists(): tmp.replace(prev)
    cur = {k: v for k, v in entry.items() if k != 'prev'}
    m['libraries'][lib_id] = dict(entry['prev'], name=name, file=idx.name, prev=cur if prev.exists() else None)
    write_manifest(m)
    log(f'rolled back {name}: {idx.name} is now the previous index ({entry["prev"].get("vectors", "?")} vectors, '
        f'method {entry["prev"].get("method", "?")}); the newer one is kept as {prev.name}')
    log('load it with:  sudo systemctl restart bibman'); sys.exit(0)

import sqlite_vec
from usearch.index import Index
con.enable_load_extension(True); sqlite_vec.load(con); con.enable_load_extension(False)
t0 = time.time()
n_nokey = con.execute('SELECT COUNT(*) FROM vec_passages_rowids WHERE id NOT IN '
                      '(SELECT id FROM passages WHERE search_id IS NOT NULL)').fetchone()[0]
log(f'database {DB_PATH}; method {args.method}; libraries: {", ".join(chosen)}')
if n_nokey:
    log(f'note: {n_nokey:,} embedded passages have no search ID and will be left out; '
        'run bibman_backfill_search_ids.py --apply first to include them')
blocked = []
for name in chosen:
    lib_id = libs[name]; idx = index_path(lib_id); prev = suffixed(idx, '.prev')
    n_all, n_key = con.execute('SELECT COUNT(*), COUNT(pa.search_id) FROM passages pa JOIN papers pp ON pp.id = pa.paper_id '
                               'WHERE pp.library_id = ?', (lib_id,)).fetchone()
    state = 'has an index' if idx.exists() else 'no index yet'
    log(f'  {name}: {n_all:,} passages, {n_key:,} with a search ID; {state}{"; a .prev backup exists" if prev.exists() else ""}')
    if prev.exists() and idx.exists() and not args.replace_prev: blocked.append(f'{name} ({prev.name})')
if blocked:
    sys.exit('STOP: these libraries already have a .prev backup from an earlier rebuild: ' + ', '.join(blocked) +
             '. Keep them by moving them elsewhere, or pass --replace-prev to overwrite them. Nothing changed.')
if args.dry_run:
    log('dry run: nothing built, nothing changed'); sys.exit(0)

CHECK_SAMPLE, CHECK_TOP10_MIN = 300, 0.97   # the check: of 300 passages spread across the library, at least 97% must
                                           # come back within the first 10 when searched with their own meaning
                                           # (the October 2026 Extragalactic index scored 99%)
SEED = 20261031                            # fixed, so a rebuild of the same data gives the same index

def check_sample(lib_id: str, method: str) -> list:
    """Up to CHECK_SAMPLE passages chosen at random from across the library: [(search_id, compressed vector)]."""
    import random
    rnd = random.Random(SEED); lo, hi = con.execute('SELECT MIN(rowid), MAX(rowid) FROM passages').fetchone()
    n_lib = con.execute('SELECT COUNT(*) FROM passages pa JOIN papers pp ON pp.id = pa.paper_id '
                        'WHERE pp.library_id = ? AND pa.search_id IS NOT NULL', (lib_id,)).fetchone()[0]
    want = min(CHECK_SAMPLE, n_lib); found = {}
    if lo is None or want == 0: return []
    for _ in range(50):   # random row numbers, so no full scan; small libraries are simply read whole
        if n_lib <= 4 * CHECK_SAMPLE:
            rows = con.execute('SELECT pa.id, pa.search_id FROM passages pa JOIN papers pp ON pp.id = pa.paper_id '
                               'WHERE pp.library_id = ? AND pa.search_id IS NOT NULL', (lib_id,)).fetchall()
        else:
            rowids = rnd.sample(range(lo, hi + 1), min(hi - lo + 1, 8 * CHECK_SAMPLE))
            rows = con.execute(f'SELECT pa.id, pa.search_id FROM passages pa JOIN papers pp ON pp.id = pa.paper_id WHERE pa.rowid IN '
                               f'({",".join("?" * len(rowids))}) AND pp.library_id = ? AND pa.search_id IS NOT NULL',
                               rowids + [lib_id]).fetchall()
        emb = dict(con.execute(f'SELECT passage_id, embedding FROM vec_passages WHERE passage_id IN ({",".join("?" * len(rows))})',
                               [r[0] for r in rows]).fetchall()) if rows else {}
        for pid, sid in rows:
            if emb.get(pid) and sid not in found:
                found[sid] = compress(np.frombuffer(emb[pid], dtype=np.float32)[:DIMS][None, :].astype(np.float32), method)[0]
        if len(found) >= want or n_lib <= 4 * CHECK_SAMPLE: break
    keys = list(found); rnd.shuffle(keys)
    return [(k, found[k]) for k in keys[:want]]

def check_index(path: Path, expected: int, sample: list) -> tuple:
    """(passed, summary) for an index file: right size, every sample passage present, and at least CHECK_TOP10_MIN of
    them found within the first 10 when searched with their own meaning, at the server's search settings."""
    ix = Index.restore(str(path), view=True); ix.expansion_search = 8   # what the server uses
    n = len(sample); present = first = top10 = top50 = 0
    for k, v in sample:
        present += ix.get(int(k)) is not None
        keys = [int(x) for x in ix.search(v, 50).keys]
        first += bool(keys) and keys[0] == int(k); top10 += int(k) in keys[:10]; top50 += int(k) in keys
    size = ix.size; del ix
    pct = lambda x: f'{x}/{n} ({100 * x / max(n, 1):.0f}%)'
    passed = size == expected and present == n and (n == 0 or top10 >= CHECK_TOP10_MIN * n)
    return passed, (f'{size:,} vectors{"" if size == expected else f" (expected {expected:,})"}; sample of {n}: present {pct(present)}, '
                    f'itself first {pct(first)}, within 10 {pct(top10)} (needs {CHECK_TOP10_MIN:.0%}), within 50 {pct(top50)}')

def install(name: str, lib_id: str, built: Path, vectors: int, method: str):
    idx = index_path(lib_id); prev = suffixed(idx, '.prev')
    m = read_manifest(); old = {k: v for k, v in (m['libraries'].get(lib_id) or {}).items() if k != 'prev'}
    if idx.exists(): idx.replace(prev)
    built.replace(idx)
    m['libraries'][lib_id] = {'name': name, 'file': idx.name, 'vectors': vectors, 'method': method,
                              'built': now_utc(), 'prev': old if (old and prev.exists()) else None}
    write_manifest(m)

def build(name: str, lib_id: str) -> str:
    """Build, check and install one library's index. Returns a one-line result.
    The passages are added in a random order (shuffled across the whole library): added one paper after another,
    the index weaves a poorer web of neighbours among each paper's very similar passages, and searches then stop
    short more often (the first per-library Extragalactic build, added paper by paper, failed its check this way).
    To shuffle without holding everything in memory, pass 1 reads the library once and appends each compressed
    passage to one of 64 temporary bucket files chosen at random; pass 2 reads one bucket at a time, shuffles it,
    and adds it to the index. The bucket files (about 300 MB for 390,000 passages) are removed afterwards."""
    idx = index_path(lib_id); tmp, failed = suffixed(idx, '.tmp'), suffixed(idx, '.failed')
    t1 = time.time(); rng = np.random.default_rng(SEED); NB = 64
    rec = np.dtype([('k', '<u8'), ('v', 'i1', (DIMS,))])
    bdir = D / f'bibman_rebuild_tmp_{lib_id}'
    if bdir.exists():
        for p in bdir.iterdir(): p.unlink()
    bdir.mkdir(exist_ok=True)
    buckets = [open(bdir / f'b{b:02d}.bin', 'wb') for b in range(NB)]
    read = no_emb = 0
    try:
        cur = con.execute('SELECT pa.id, pa.search_id FROM passages pa JOIN papers pp ON pp.id = pa.paper_id '
                          'WHERE pp.library_id = ? AND pa.search_id IS NOT NULL', (lib_id,))
        while True:
            rows = cur.fetchmany(BATCH)   # one batch at a time keeps memory low on a 1 GB machine
            if not rows: break
            key_of = dict(rows)
            emb = con.execute(f'SELECT passage_id, embedding FROM vec_passages WHERE passage_id IN '
                              f'({",".join("?" * len(rows))})', list(key_of)).fetchall()
            got = [(key_of[pid], blob) for pid, blob in emb if blob]
            no_emb += len(rows) - len(got)
            if got:
                R = np.empty(len(got), dtype=rec)
                R['k'] = [k for k, _ in got]
                R['v'] = compress(np.stack([np.frombuffer(b, dtype=np.float32)[:DIMS] for _, b in got]).astype(np.float32), args.method)
                where = rng.integers(0, NB, len(got))
                for b in range(NB):
                    sel = R[where == b]
                    if len(sel): sel.tofile(buckets[b])
                read += len(got)
            if read and read % 50000 < BATCH: log(f'    {name}: {read:,} read')
    finally:
        for fh in buckets: fh.close()
    if read == 0:
        for p in bdir.iterdir(): p.unlink()
        bdir.rmdir()
        return f'{name}: no embedded passages yet, so no index built (the server compares such a library directly)'
    log(f'    {name}: all {read:,} read; adding them to the index in random order ...')
    index = Index(ndim=DIMS, dtype='i8', metric='cos', connectivity=16, expansion_add=128, expansion_search=8)
    added = 0
    for b in range(NB):
        R = np.fromfile(bdir / f'b{b:02d}.bin', dtype=rec)
        R = R[rng.permutation(len(R))]
        for i in range(0, len(R), BATCH):
            index.add(R['k'][i:i + BATCH].astype(np.uint64), np.ascontiguousarray(R['v'][i:i + BATCH]), threads=1)
        added += len(R); (bdir / f'b{b:02d}.bin').unlink()
        if added % 50000 < len(R): log(f'    {name}: {added:,} added')
    bdir.rmdir()
    index.save(str(tmp)); del index
    log(f'    {name}: saved; checking ...')
    passed, summary = check_index(tmp, added, check_sample(lib_id, args.method))
    if not passed:
        tmp.replace(failed)
        return (f'{name}: check FAILED: {summary}. Its current index is left untouched; the new one is kept as '
                f'{failed.name} (re-check it with --recheck --library {name})')
    install(name, lib_id, tmp, added, args.method)
    return (f'{name}: installed {idx.name}: {added:,} vectors, {idx.stat().st_size / 2**20:.1f} MB, method {args.method}; '
            f'check passed: {summary}{f"; {no_emb:,} passage(s) without an embedding yet (left out)" if no_emb else ""}; '
            f'{time.time() - t1:.0f}s')

def recheck(name: str, lib_id: str) -> str:
    """Check a library's kept .failed index again (the check may have changed), and install it if it passes."""
    idx = index_path(lib_id); failed = suffixed(idx, '.failed')
    if not failed.exists(): return f'{name}: no {failed.name} to re-check'
    ix = Index.restore(str(failed), view=True); n = ix.size; del ix
    passed, summary = check_index(failed, n, check_sample(lib_id, args.method))
    if not passed: return f'{name}: re-check FAILED: {summary}; {failed.name} kept, current index untouched'
    install(name, lib_id, failed, n, args.method)
    return f'{name}: re-check passed: {summary}; installed as {idx.name}'

results = []
for name in sorted(chosen, key=lambda n: n == 'Extragalactic'):  # small ones first: done in seconds, so you see early that all is well
    log(f'{"re-checking" if args.recheck else "building"} {name} ...')
    results.append((recheck if args.recheck else build)(name, libs[name])); log('  ' + results[-1])
con.close()
log(f'finished in {time.time() - t0:.0f}s:')
for r in results: log('  ' + r)
log('BibMan still uses the old index until restarted:  sudo systemctl restart bibman')
