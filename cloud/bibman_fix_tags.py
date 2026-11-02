#!/usr/bin/env python3
"""
One-time repair of the tag table (2 Nov 2026), and removal of tags and @mentions left behind by deleted notes.

1. Databases made before note tagging still have the rule UNIQUE(paper_id, user_id, label_id) on paper_tags: a person
   could use a label only ONCE per paper, the paper itself and all its notes together. Further uses (e.g. TCAN26 on a
   second highlight) were silently ignored. This rebuilds the table with the intended rule: a label once per person on
   the paper as a whole, and once on EACH of its notes. Every existing tag is kept. The old table is kept too, renamed
   paper_tags_old_rule_<date and time>, as a backup (to be deleted after a week or so).
2. Deleting a note used to leave its tags and @mentions behind, pointing at a note that no longer exists; they made
   the "In notes: ×n" counts too high and could make a paper match a tag filter. They are listed, written in full to
   a backup TSV next to the database, and deleted. (Tags and mentions of deleted papers too, should there be any.)

DRY RUN by default (the database is opened read-only); --apply makes the changes, the rebuild in one transaction.
Running it again after --apply finds nothing to do. Safe while BibMan is running.

    sudo -u bibman /home/bibman/bibman/venv/bin/python ~/bibman_fix_tags.py
    sudo -u bibman /home/bibman/bibman/venv/bin/python ~/bibman_fix_tags.py --apply
"""
import os, re, sys, csv, sqlite3, argparse
from datetime import datetime, timezone

# ── the same as in bibman_e2micro_server.py (keep the two alike) ──────────────────────────────────────────────────
PAPER_TAGS_TABLE = '''CREATE TABLE {name} (
    id            TEXT PRIMARY KEY,
    paper_id      TEXT NOT NULL,
    user_id       TEXT NOT NULL,
    label_id      TEXT NOT NULL,
    annotation_id TEXT DEFAULT NULL,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY(label_id) REFERENCES user_tag_labels(id) ON DELETE CASCADE)'''
PAPER_TAGS_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_paper_tags_place "
                    "ON paper_tags(paper_id, user_id, label_id, IFNULL(annotation_id, ''))")

def paper_tags_has_old_rule(conn) -> bool:
    r = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='paper_tags'").fetchone()
    return bool(r and r[0]) and 'unique(paper_id,user_id,label_id)' in re.sub(r'\s+', '', r[0]).lower()

def fix_paper_tags_rule(conn):
    """Give paper_tags the per-note rule. An old table is rebuilt with every row kept, and kept itself, renamed
    paper_tags_old_rule_<date>, as a backup. Returns the number of tags copied, or None if nothing needed doing."""
    if not paper_tags_has_old_rule(conn):
        conn.execute(PAPER_TAGS_INDEX)
        conn.commit()
        return None
    backup = 'paper_tags_old_rule_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    conn.commit()
    conn.execute('PRAGMA foreign_keys = OFF')   # the documented way to rebuild a table; checked again before COMMIT
    try:
        conn.execute('BEGIN IMMEDIATE')
        try:
            if not paper_tags_has_old_rule(conn):   # another process fixed it meanwhile
                conn.execute('ROLLBACK')
                return None
            conn.execute('DROP TABLE IF EXISTS paper_tags_new')
            conn.execute(PAPER_TAGS_TABLE.format(name='paper_tags_new'))
            conn.execute('INSERT INTO paper_tags_new (id, paper_id, user_id, label_id, annotation_id, created_at) '
                         'SELECT id, paper_id, user_id, label_id, annotation_id, created_at FROM paper_tags')
            n_old = conn.execute('SELECT COUNT(*) FROM paper_tags').fetchone()[0]
            n_new = conn.execute('SELECT COUNT(*) FROM paper_tags_new').fetchone()[0]
            if n_old != n_new:
                raise RuntimeError(f'copied {n_new} of {n_old} tags')
            conn.execute(f'ALTER TABLE paper_tags RENAME TO {backup}')
            conn.execute('ALTER TABLE paper_tags_new RENAME TO paper_tags')
            conn.execute(PAPER_TAGS_INDEX)
            if conn.execute('PRAGMA foreign_key_check(paper_tags)').fetchone():
                raise RuntimeError('a tag refers to a missing paper or label')
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
    finally:
        conn.execute('PRAGMA foreign_keys = ON')
    print(f'tag table: rule changed to one label per note; {n_new} tags kept; old table kept as {backup}')
    return n_new
# ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

LEFTOVER = ("((annotation_id IS NOT NULL AND annotation_id != '' AND annotation_id NOT IN (SELECT id FROM annotations)) "
            "OR paper_id NOT IN (SELECT id FROM papers))")

ap = argparse.ArgumentParser(); ap.add_argument('--apply', action='store_true'); args = ap.parse_args()
DB = os.environ.get('DB_PATH', '/home/bibman/bibman.db')
con = sqlite3.connect(DB, timeout=60) if args.apply else sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
con.row_factory = sqlite3.Row
print(f'{"APPLY" if args.apply else "DRY RUN (nothing will be changed)"}: {DB}')

old_rule = paper_tags_has_old_rule(con)
n_tags = con.execute('SELECT COUNT(*) FROM paper_tags').fetchone()[0]
n_note = con.execute("SELECT COUNT(*) FROM paper_tags WHERE annotation_id IS NOT NULL AND annotation_id != ''").fetchone()[0]
print(f'1. tag table: {n_tags} tags ({n_tags - n_note} on papers as a whole, {n_note} on notes)')
print('   rule: ' + ('OLD (a label once per paper per person, paper and notes together): will be changed to once per note'
                   if old_rule else 'already one label per note: nothing to change'))

tags = list(con.execute(f'''SELECT pt.*, l.label FROM paper_tags pt LEFT JOIN user_tag_labels l ON l.id = pt.label_id
                            WHERE {LEFTOVER}
                            ORDER BY pt.created_at'''))
ments = list(con.execute(f'SELECT * FROM mentions WHERE {LEFTOVER} ORDER BY created_at'))
print(f'2. left behind by deleted notes or papers: {len(tags)} tags, {len(ments)} @mentions')
for r in tags[:30]:
    print(f'      tag "{r["label"]}" by @{r["user_id"]} ({r["created_at"]}) on a deleted {"note" if r["annotation_id"] else "paper"}')
for r in ments[:30]:
    print(f'      @mention of @{r["mentioned_user"]} by @{r["mentioned_by"]} ({r["created_at"]}) on a deleted '
          f'{"note" if r["annotation_id"] else "paper"}: "{(r["note"] or "")[:60]}"')
if len(tags) > 30 or len(ments) > 30: print('      ... (all of them go in the backup file)')

if not (old_rule or tags or ments): print('nothing to do'); sys.exit(0)
if not args.apply: print('dry run OK: run again with --apply to make these changes'); sys.exit(0)

if tags or ments:
    backup = os.path.join(os.path.dirname(DB), f'tags_mentions_leftover_backup_{datetime.now():%Y%m%d}.tsv')
    with open(backup, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f, delimiter='\t')
        for name, rows in (('paper_tags', tags), ('mentions', ments)):
            if rows:
                w.writerow(['table'] + list(rows[0].keys()))
                for r in rows: w.writerow([name] + [r[c] for c in r.keys()])
    print(f'backup of the {len(tags)} tags and {len(ments)} mentions to be deleted: {backup}')

fix_paper_tags_rule(con)
con.execute('BEGIN IMMEDIATE')
try:
    for table, rows in (('paper_tags', tags), ('mentions', ments)):
        ids = [r['id'] for r in rows]
        for i in range(0, len(ids), 500):
            ch = ids[i:i + 500]
            con.execute(f'DELETE FROM {table} WHERE id IN ({",".join("?" * len(ch))})', ch)
    con.execute('COMMIT')
except Exception:
    con.execute('ROLLBACK'); raise
left = [con.execute(f'SELECT COUNT(*) FROM {t} WHERE {LEFTOVER}').fetchone()[0] for t in ('paper_tags', 'mentions')]
idx = con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='ux_paper_tags_place'").fetchone()
print(f'done. Tags now: {con.execute("SELECT COUNT(*) FROM paper_tags").fetchone()[0]}; '
      f'rule: {"OLD (not changed!)" if paper_tags_has_old_rule(con) else "one label per note"}'
      f'{"" if idx else " (index MISSING!)"}; left behind: {left[0]} tags, {left[1]} mentions')
