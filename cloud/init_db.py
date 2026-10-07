#!/usr/bin/env python3
"""
Create an EMPTY BibMan database for a new instance.

    DB_PATH=/home/bibman/bibman.db LIBRARY_NAME=MyLibrary python3 init_db.py

Builds every table from schema.sql (with the sqlite-vec extension loaded, which the vec0
tables need) and adds one library named $LIBRARY_NAME. Refuses to touch an existing file,
so it can never overwrite a real library.
"""
import os, sys, uuid, sqlite3
from pathlib import Path
import sqlite_vec

db = Path(os.environ.get('DB_PATH', '/home/bibman/bibman.db'))
lib = os.environ.get('LIBRARY_NAME', 'MyLibrary')
if db.exists() and db.stat().st_size > 0: sys.exit(f'{db} already exists and is not empty, refusing to overwrite it.')
db.parent.mkdir(parents=True, exist_ok=True)
conn = sqlite3.connect(db)
conn.enable_load_extension(True); sqlite_vec.load(conn); conn.enable_load_extension(False)
conn.execute('PRAGMA journal_mode=WAL')
conn.executescript((Path(__file__).parent / 'schema.sql').read_text())
conn.execute('INSERT INTO libraries (id, name) VALUES (?, ?)', (str(uuid.uuid4()), lib))
conn.commit(); conn.close()
print(f'Created empty BibMan database at {db} with library "{lib}".')
