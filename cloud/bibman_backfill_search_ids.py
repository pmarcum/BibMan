#!/usr/bin/env python3
"""
Fill in the missing search IDs that the semantic-search index uses as keys.

Passages added before late April 2026 got a search_id from a one-off migration; passages added later
did not (the add-paper code never set it, fixed in the 6 Oct 2026 server). Without an ID a passage can
never enter the search index, so meaning-based search cannot find it.

    search_id = first 16 hex digits of the passage UUID (dashes removed), as an integer, masked to 63 bits

Safe by design:
  * DRY RUN by default: shows what it would do and changes nothing. Add --apply to write.
  * Before writing, it recomputes the IDs of existing passages and refuses to continue unless the formula
    reproduces every one of them, and unless no new ID would collide with an existing one.
  * Only rows where search_id IS NULL are touched; existing IDs are never changed. One transaction:
    it either completes or changes nothing.

Run as the bibman user, with BibMan's own Python:
    sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_backfill_search_ids.py            # dry run
    sudo -u bibman /home/bibman/bibman/venv/bin/python bibman_backfill_search_ids.py --apply    # write
"""
import os, sys, sqlite3

DB    = os.environ.get('DB_PATH', '/home/bibman/bibman.db')
MASK  = 0x7FFFFFFFFFFFFFFF
APPLY = '--apply' in sys.argv

def search_id(passage_uuid: str) -> int:
    return int(passage_uuid.replace('-', '')[:16], 16) & MASK

con = sqlite3.connect(DB, timeout=60) if APPLY else sqlite3.connect(f'file:{DB}?mode=ro', uri=True, timeout=60)
total, missing = con.execute('SELECT COUNT(*), SUM(search_id IS NULL) FROM passages').fetchone()
missing = missing or 0
print(f'{"APPLY" if APPLY else "DRY RUN (nothing will be changed)"}: {DB}')
print(f'passages: {total:,}   without search ID: {missing:,}')
if not missing:
    sys.exit('nothing to do: every passage already has a search ID')

existing = con.execute('SELECT id, search_id FROM passages WHERE search_id IS NOT NULL').fetchall()
bad = [(i, s) for i, s in existing if search_id(i) != s]
print(f'formula check: reproduces {len(existing) - len(bad):,} of {len(existing):,} existing IDs')
if bad:
    sys.exit(f'STOP: the formula does not reproduce {len(bad)} existing IDs (e.g. {bad[0][0]}); nothing changed')

todo  = [(search_id(i), i) for (i,) in con.execute('SELECT id FROM passages WHERE search_id IS NULL')]
taken = {s for _, s in existing}
clash = [i for s, i in todo if s in taken]
dupes = len(todo) - len({s for s, _ in todo})
print(f'new IDs: {len(todo):,}   colliding with existing: {len(clash)}   duplicated among new: {dupes}')
if clash or dupes:
    sys.exit('STOP: some new IDs would collide; nothing changed')

if not APPLY:
    print('dry run OK: run again with --apply to write these IDs')
    sys.exit(0)

with con:  # one transaction: all or nothing
    con.executemany('UPDATE passages SET search_id=? WHERE id=? AND search_id IS NULL', todo)
left = con.execute('SELECT COUNT(*) FROM passages WHERE search_id IS NULL').fetchone()[0]
print(f'done: wrote {len(todo):,} search IDs; passages still without one: {left}')
