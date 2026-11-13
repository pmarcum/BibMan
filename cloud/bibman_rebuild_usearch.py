#!/usr/bin/env python3
"""
BibMan semantic-search index rebuild (one index per library)
============================================================
Rebuilds the USearch indexes from the embeddings already stored in the database (no Gemini calls). Each library
gets its own index file, so meaning-based search only ever looks at the current library's passages.
--sync brings existing indexes up to date instead (adds new passages, removes deleted or moved ones) in minutes; the
server runs it after each nightly job, so a full rebuild is only needed occasionally (every few months, to tidy up).

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
  * BibMan notices new indexes by itself (it checks the list file before each search), so no restart is needed.

Compression method (how each 768-dim float vector becomes int8), recorded per library in the list file so the
server compresses search queries the same way:
  A  x127, no normalizing           (how the April 2026 index was built)
  B  normalize, then x127
  C  scale each vector to its own maximum, then x127   (default; most precise for cosine search)

Usage (as the bibman user, with BibMan's Python; a full rebuild takes hours on an e2-micro, so run it when nobody
is using BibMan or gooTeX; a small library takes seconds):
  sudo -u bibman /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py --dry-run
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py                 # all
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py --library Satellites
  sudo -u bibman /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py --rollback --library Satellites
  sudo -u bibman /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py --recheck --library Extragalactic
  sudo -u bibman nice -n 19 /home/bibman/bibman/venv/bin/python /home/bibman/bibman/cloud/bibman_rebuild_usearch.py --sync      # what the nightly job runs
  (add --replace-prev once you are happy with the current indexes; add --method A/B/C to choose compression)
"""
import os, sys, json, time, fcntl, sqlite3, argparse
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
ap.add_argument('--sync', action='store_true', help="bring existing indexes up to date (add new passages, remove gone ones)")
args = ap.parse_args()

DB_PATH = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
D = DB_PATH.parent
MANIFEST = D / 'bibman_768_i8.libraries.json'
def index_path(lib_id: str) -> Path: return D / f'bibman_768_i8.lib-{lib_id}.usearch'
def suffixed(p: Path, s: str) -> Path: return p.with_name(p.name + s)
def keys_path(lib_id: str) -> Path: return D / f'bibman_768_i8.lib-{lib_id}.keys.npy'   # the index's passage IDs, so a
                                                    # sync can see what changed without reading the whole index file
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
    kp = keys_path(lib_id); kprev, kswap = suffixed(kp, '.prev'), suffixed(kp, '.swap')
    if kp.exists(): kp.replace(kswap)
    if kprev.exists(): kprev.replace(kp)
    if kswap.exists(): kswap.replace(kprev)
    cur = {k: v for k, v in entry.items() if k != 'prev'}
    m['libraries'][lib_id] = dict(entry['prev'], name=name, file=idx.name, prev=cur if prev.exists() else None)
    write_manifest(m)
    log(f'rolled back {name}: {idx.name} is now the previous index ({entry["prev"].get("vectors", "?")} vectors, '
        f'method {entry["prev"].get("method", "?")}); the newer one is kept as {prev.name}')
    log('BibMan loads it by itself before its next search (no restart needed)'); sys.exit(0)

import sqlite_vec
from usearch.index import Index
con.enable_load_extension(True); sqlite_vec.load(con); con.enable_load_extension(False)
t0 = time.time()
if not args.dry_run:   # one rebuild or sync at a time (the nightly sync and a hand-started rebuild must not overlap)
    _lock = open(D / 'bibman_768_i8.lock', 'w')
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit('STOP: another rebuild or sync of the search indexes is running; nothing changed')
n_nokey = con.execute('SELECT COUNT(*) FROM vec_passages_rowids WHERE id NOT IN '
                      '(SELECT id FROM passages WHERE search_id IS NOT NULL)').fetchone()[0]
log(f'database {DB_PATH}; method {args.method}; libraries: {", ".join(chosen)}')
if n_nokey:
    log(f'note: {n_nokey:,} embedded passages have no search ID and will be left out; '
        'run bibman_backfill_search_ids.py --apply first to include them')
blocked = []
for name in ([] if args.sync else chosen):   # a sync keeps one backup per library and replaces it each time
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

def check_sample(lib_id: str, method: str, CHECK_SAMPLE: int = CHECK_SAMPLE) -> list:
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

def install(name: str, lib_id: str, built: Path, vectors: int, method: str, synced: bool = False, keys=None):
    idx = index_path(lib_id); prev = suffixed(idx, '.prev'); kp = keys_path(lib_id)
    m = read_manifest(); old = {k: v for k, v in (m['libraries'].get(lib_id) or {}).items() if k != 'prev'}
    if keys is None:   # e.g. a re-checked .failed index: read its IDs from the file itself
        ix = Index.restore(str(built), view=True); keys = np.array([int(k) for k in ix.keys], dtype=np.uint64); del ix
    ktmp = suffixed(kp, '.tmp.npy'); np.save(ktmp, np.sort(np.asarray(keys, dtype=np.uint64)))
    if idx.exists(): idx.replace(prev)
    if kp.exists(): kp.replace(suffixed(kp, '.prev'))
    built.replace(idx); ktmp.replace(kp)
    m['libraries'][lib_id] = {'name': name, 'file': idx.name, 'vectors': vectors, 'method': method,
                              'built': old.get('built', now_utc()) if synced else now_utc(),
                              'synced': now_utc() if synced else None, 'prev': old if (old and prev.exists()) else None}
    write_manifest(m)

def build(name: str, lib_id: str) -> str:
    """Build, check and install one library's index. Returns a one-line result.
    The passages are added in a random order (shuffled across the whole library): added one paper after another,
    the index weaves a poorer web of neighbors among each paper's very similar passages, and searches then stop
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
    added = 0; all_keys = []
    for b in range(NB):
        R = np.fromfile(bdir / f'b{b:02d}.bin', dtype=rec)
        R = R[rng.permutation(len(R))]; all_keys.append(R['k'].astype(np.uint64))
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
    install(name, lib_id, tmp, added, args.method, keys=np.concatenate(all_keys))
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

SYNC_SPREAD = 50   # a sync's check: the passages it added (up to 300) plus 50 already in the index, spread across it

_embedded = None
def embedded_ids() -> set:
    """IDs of all passages that have an embedding (read once per run)."""
    global _embedded
    if _embedded is None: _embedded = {r[0] for r in con.execute('SELECT id FROM vec_passages_rowids')}
    return _embedded

def sync(name: str, lib_id: str) -> str:
    """Bring a library's index up to date: add its passages that are not in the index yet (new papers, papers moved
    in, re-extracted papers), in random order, and remove those that are no longer the library's (deleted, moved
    out, replaced by a re-extraction). Afterwards the index holds exactly the library's embedded passages. A library
    without an index gets a full build. The result is checked before it replaces the index, as for a rebuild."""
    idx = index_path(lib_id); tmp, failed = suffixed(idx, '.tmp'), suffixed(idx, '.failed')
    entry = read_manifest()['libraries'].get(lib_id)
    if not idx.exists() or not entry:
        log(f'    {name}: no index yet, so a full build')
        return build(name, lib_id)
    t1 = time.time(); method = entry.get('method') or 'C'
    def lap(what, t=[time.time()]):   # how long each stage took, for the log
        now = time.time(); log(f'    {name}: {what} ({now - t[0]:.0f}s)'); t[0] = now
    emb = embedded_ids(); lap('read which passages have embeddings')
    wanted = {sid: pid for pid, sid in con.execute('SELECT pa.id, pa.search_id FROM passages pa JOIN papers pp ON pp.id = pa.paper_id '
                                                   'WHERE pp.library_id = ? AND pa.search_id IS NOT NULL', (lib_id,)) if pid in emb}
    lap(f'read the library\'s {len(wanted):,} embedded passages')
    kp = keys_path(lib_id); have = None
    if kp.exists():
        k = np.load(kp)
        if len(k) == entry.get('vectors'): have = {int(x) for x in k}
    if have is None:   # no (or an outdated) ID list: read the IDs from the index file itself (slow, once)
        ix = Index.restore(str(idx), view=True); have = {int(x) for x in ix.keys}; del ix
        lap(f"read the index's {len(have):,} passage IDs from the index file (no ID list yet)")
    else:
        lap(f"read the index's {len(have):,} passage IDs")
    to_add = [sid for sid in wanted if sid not in have]
    to_remove = [k for k in have if k not in wanted]
    rng = np.random.default_rng(SEED); rng.shuffle(to_add); skipped = 0; new_k, new_v = [], []
    for i in range(0, len(to_add), 500):   # the new passages' embeddings, before touching the index
        keys = to_add[i:i + 500]; pids = [wanted[k] for k in keys]
        blobs = dict(con.execute(f'SELECT passage_id, embedding FROM vec_passages WHERE passage_id IN ({",".join("?" * len(pids))})', pids).fetchall())
        got = [(k, blobs[wanted[k]]) for k in keys if blobs.get(wanted[k])]
        skipped += len(keys) - len(got)
        if got:
            new_k += [k for k, _ in got]
            new_v.append(compress(np.stack([np.frombuffer(b, dtype=np.float32)[:DIMS] for _, b in got]).astype(np.float32), method))
    note = f'; {skipped:,} without embedding data yet (left out)' if skipped else ''
    if not new_k and not to_remove:
        if kp.exists() and len(have) == entry.get('vectors'):
            return f'{name}: already up to date ({len(have):,} passages{note}); {time.time() - t1:.0f}s'
        install_keys_only = np.array(sorted(have), dtype=np.uint64)   # first sync after this change: keep the ID list from now on
        ktmp = suffixed(kp, '.tmp.npy'); np.save(ktmp, install_keys_only); ktmp.replace(kp)
        m = read_manifest(); m['libraries'][lib_id]['vectors'] = len(have); write_manifest(m)
        return f'{name}: already up to date ({len(have):,} passages{note}); ID list written; {time.time() - t1:.0f}s'
    lap(f'{len(new_k):,} to add, {len(to_remove):,} to remove')
    index = Index.restore(str(idx))   # into memory, so it can be changed (a rebuild needs as much)
    lap('loaded the index')
    if to_remove: index.remove(np.array(to_remove, dtype=np.uint64))
    V = np.concatenate(new_v) if new_v else np.zeros((0, DIMS), np.int8)
    for i in range(0, len(new_k), 500):
        index.add(np.array(new_k[i:i + 500], dtype=np.uint64), V[i:i + 500], threads=1)
    sample = [(new_k[j], V[j]) for j in range(min(len(new_k), CHECK_SAMPLE))]
    expected = index.size
    keys_now = np.array(sorted((have - set(to_remove)) | set(new_k)), dtype=np.uint64)
    del have
    index.save(str(tmp)); del index
    lap('changed and saved the index')
    passed, summary = check_index(tmp, expected, sample + check_sample(lib_id, method, SYNC_SPREAD))
    lap('checked it')
    change = f'{len(new_k):,} added, {len(to_remove):,} removed'
    if not passed or expected != len(keys_now):
        tmp.replace(failed)
        return (f'{name}: sync check FAILED ({change}; {summary}{"" if expected == len(keys_now) else f"; index holds {expected:,}, expected {len(keys_now):,}"}). '
                f'Its current index is left untouched; the new one is kept as {failed.name}')
    install(name, lib_id, tmp, expected, method, synced=True, keys=keys_now)
    return f'{name}: synced: {change}, now {expected:,} passages{note}; check passed: {summary}; {time.time() - t1:.0f}s'

results = []
for name in sorted(chosen, key=lambda n: n == 'Extragalactic'):  # small ones first: done in seconds, so you see early that all is well
    action, verb = (recheck, 're-checking') if args.recheck else (sync, 'syncing') if args.sync else (build, 'building')
    log(f'{verb} {name} ...')
    results.append(action(name, libs[name])); log('  ' + results[-1])
con.close()
log(f'finished in {time.time() - t0:.0f}s:')
for r in results: log('  ' + r)
log('BibMan loads the new indexes by itself before its next search (no restart needed)')
