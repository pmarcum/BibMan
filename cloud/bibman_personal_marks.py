#!/usr/bin/env python3
"""
One-off switch to personal Key paper / Pinned / Follow-up marks (29 Oct 2026).

Before: each paper had one shared switch per mark (papers.key_paper / pinned / followup), and each note one
shared switch per mark (annotations.flag_key_point / flag_pinned / flag_follow_up).
After: marks are per person, like tags: paper_flags (paper + person) and annotation_flags (note + person).

This script copies today's shared marks into the per-person tables:
  * paper marks go to ONE person, given with --user (on the reference server everything so far was made by
    one person). Their paper_flags rows are made to match exactly what the shared switches show today; any
    older row that disagrees (for example a pin removed since) is corrected, and listed.
  * note marks go to each note's author (annotations.username).
The shared columns are left untouched as a backup. Run it once, just before installing the server that
reads the new tables.

Safe by design: DRY RUN by default (shows what it would do, changes nothing); --apply writes everything in
one transaction (all or nothing); running it again changes nothing more.

Run as the bibman user, with BibMan's Python:
    sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_personal_marks.py --user pamelammarcum
    sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_personal_marks.py --user pamelammarcum --apply
"""
import os, sys, uuid, sqlite3, argparse

ap = argparse.ArgumentParser()
ap.add_argument('--user', required=True, help='username that receives the existing paper marks')
ap.add_argument('--apply', action='store_true')
args = ap.parse_args()
DB = os.environ.get('DB_PATH', '/home/bibman/bibman.db')
PAPER = ('key_paper', 'pinned', 'followup')
NOTE = {'flag_key_point': 'key_point', 'flag_pinned': 'pinned', 'flag_follow_up': 'followup'}

con = sqlite3.connect(DB, timeout=60, isolation_level=None) if args.apply else \
      sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60, isolation_level=None)
con.row_factory = sqlite3.Row
print(f'{"APPLY" if args.apply else "DRY RUN (nothing will be changed)"}: {DB}   user: {args.user}')

def has_unique(table, cols):
    for ix in con.execute(f'PRAGMA index_list({table})'):
        if ix['unique'] and [r['name'] for r in con.execute(f'PRAGMA index_info({ix["name"]})')] == cols:
            return True
    return False
for t, cols in (('paper_flags', ['paper_id', 'username']), ('annotation_flags', ['annotation_id', 'username'])):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
        sys.exit(f'STOP: table {t} is missing (start the new server once, or create it from schema.sql); nothing changed')
    if not has_unique(t, cols):
        sys.exit(f'STOP: table {t} has no UNIQUE({", ".join(cols)}); nothing changed')

users = [r[0] for r in con.execute('SELECT DISTINCT username FROM annotations WHERE username IS NOT NULL')]
if users and args.user not in users:
    sys.exit(f'STOP: "{args.user}" is not among the note authors {users}; check the spelling. Nothing changed')

# --- paper marks -------------------------------------------------------------------------------------
want = {r['id']: (r['bibkey'], {m: int(bool(r[m])) for m in PAPER})
        for r in con.execute('SELECT id, bibkey, key_paper, pinned, followup FROM papers')}
have = {r['paper_id']: {m: int(bool(r[m])) for m in PAPER}
        for r in con.execute('SELECT paper_id, key_paper, pinned, followup FROM paper_flags WHERE username=?', (args.user,))}
paper_ops, corrected = [], []
for pid, (bibkey, w) in want.items():
    h = have.get(pid)
    if h == w or (h is None and not any(w.values())):
        continue
    paper_ops.append((pid, w))
    if h is not None and any(h[m] and not w[m] for m in PAPER):
        corrected.append(f'{bibkey}: old row had {", ".join(m for m in PAPER if h[m] and not w[m])}, '
                         'which the paper no longer shows: cleared')
totals = {m: sum(w[m] for _, w in want.values()) for m in PAPER}
print(f'paper marks today (shared switches): key paper {totals["key_paper"]}, pinned {totals["pinned"]}, '
      f'follow-up {totals["followup"]}')
print(f'paper_flags rows for {args.user} to create or correct: {len(paper_ops)}')
for line in corrected:
    print('   ', line)

# --- note marks --------------------------------------------------------------------------------------
note_ops = []
for r in con.execute('SELECT id, username, flag_key_point, flag_pinned, flag_follow_up FROM annotations '
                     'WHERE flag_key_point=1 OR flag_pinned=1 OR flag_follow_up=1'):
    w = {col: int(bool(r[api])) for api, col in NOTE.items()}
    h = con.execute('SELECT key_point, pinned, followup FROM annotation_flags WHERE annotation_id=? AND username=?',
                    (r['id'], r['username'])).fetchone()
    if h is None or {c: int(bool(h[c])) for c in w} != w:
        note_ops.append((r['id'], r['username'] or args.user, w))
print(f'note marks to copy to their authors: {len(note_ops)}')

if not paper_ops and not note_ops:
    print('nothing to do: the personal tables already match'); sys.exit(0)
if not args.apply:
    print('dry run OK: run again with --apply to write these'); sys.exit(0)

def upsert(table, key_col, key, user, values):
    con.execute(f'INSERT INTO {table} (id, {key_col}, username) VALUES (?,?,?) '
                f'ON CONFLICT({key_col}, username) DO NOTHING', (str(uuid.uuid4()), key, user))
    con.execute(f'UPDATE {table} SET {", ".join(f"{c}=?" for c in values)} WHERE {key_col}=? AND username=?',
                list(values.values()) + [key, user])

con.execute('BEGIN IMMEDIATE')
try:
    for pid, w in paper_ops:
        upsert('paper_flags', 'paper_id', pid, args.user, w)
    for aid, user, w in note_ops:
        upsert('annotation_flags', 'annotation_id', aid, user, w)
    con.execute('COMMIT')
except Exception:
    con.execute('ROLLBACK'); raise
n = con.execute('SELECT SUM(key_paper=1), SUM(pinned=1), SUM(followup=1) FROM paper_flags WHERE username=?',
                (args.user,)).fetchone()
print(f'done. {args.user} now has: key paper {n[0] or 0}, pinned {n[1] or 0}, follow-up {n[2] or 0}')
