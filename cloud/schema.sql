-- BibMan database schema (exported from the production database; definitions only, no data).
-- Do not run this with the plain sqlite3 CLI: the vec0 tables need the sqlite-vec extension.
-- Use:  python3 init_db.py   (creates an empty bibman.db at $DB_PATH from this file)
-- FTS5 / vec0 shadow tables are created automatically and are intentionally omitted.

CREATE TABLE IF NOT EXISTS "annotations" (
        id                    TEXT PRIMARY KEY,
        paper_id              TEXT NOT NULL,
        passage_id            TEXT,
        annotation_type       TEXT DEFAULT 'paper',
        quote                 TEXT,
        user_note             TEXT,
        bookmarked            INTEGER DEFAULT 0,
        bookmarked_by         TEXT,
        challenges_convention INTEGER DEFAULT 0,
        created_at            TEXT DEFAULT (datetime('now')), coords TEXT, username TEXT, flag_key_point INTEGER DEFAULT 0, flag_follow_up INTEGER DEFAULT 0, flag_pinned INTEGER DEFAULT 0,
        FOREIGN KEY (paper_id) REFERENCES papers(id)
    );

CREATE TABLE corpus_terms (
    id          TEXT PRIMARY KEY,
    library_id  TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    term        TEXT NOT NULL,
    frequency   INTEGER NOT NULL DEFAULT 1,
    is_phrase   INTEGER NOT NULL DEFAULT 0,    -- boolean: single word vs phrase
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (library_id, term)
);

CREATE TABLE journals (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name    TEXT NOT NULL,
            abbreviation TEXT NOT NULL,
            latex_macro  TEXT,
            ads_bibstem  TEXT,
            UNIQUE(full_name)
        );

CREATE TABLE libraries (
    id          TEXT PRIMARY KEY,              -- UUID string
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS "paper_project_labels" (
        paper_id  TEXT NOT NULL,
        label_id  TEXT NOT NULL,
        PRIMARY KEY (paper_id, label_id),
        FOREIGN KEY (paper_id)  REFERENCES papers(id),
        FOREIGN KEY (label_id)  REFERENCES project_labels(id)
    );

CREATE TABLE papers (
    id              TEXT PRIMARY KEY,
    library_id      TEXT NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,

    -- Identifiers
    file_id         TEXT,                      -- Google Drive file ID (v1)
    bibkey          TEXT NOT NULL,             -- e.g. "kennicutt+1998araa36_189"
    bibcode         TEXT,                      -- NASA ADS bibcode
    doi             TEXT,

    -- Bibliographic content
    title           TEXT,
    authors         TEXT,
    year            INTEGER,
    journal         TEXT,
    bibtex          TEXT,                      -- full bibtex string for .bib export

    -- PDF
    pdf_url         TEXT,
    pdf_extracted   INTEGER NOT NULL DEFAULT 0, -- boolean: 0=no 1=yes

    -- Workflow
    read_status     TEXT NOT NULL DEFAULT 'unread'
                    CHECK (read_status IN ('unread', 'reading', 'read')),

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), remember INTEGER DEFAULT 0, key_paper INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0, followup INTEGER DEFAULT 0, volume TEXT, pages TEXT, pubtype TEXT, content_source_url TEXT, abstract TEXT, added_by TEXT, tags TEXT, synonyms_generated_at DATETIME,

    UNIQUE (library_id, bibkey)
);

CREATE TABLE passages (
    id              TEXT PRIMARY KEY,
    paper_id        TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,

    -- Location within PDF
    page_number     INTEGER NOT NULL,
    passage_index   INTEGER NOT NULL,          -- ordering within page

    -- Fractional coordinates (zoom-invariant, from v1)
    x1              REAL,
    y1              REAL,
    x2              REAL,
    y2              REAL,
    h2w_ratio       REAL,                      -- page height-to-width ratio

    -- Content
    text            TEXT NOT NULL,

    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')), search_id INTEGER,

    UNIQUE (paper_id, page_number, passage_index)
);

CREATE VIRTUAL TABLE passages_fts
    USING fts5(text, content='passages', content_rowid='rowid')
/* passages_fts(text) */;

CREATE TABLE project_labels (
        id         TEXT PRIMARY KEY,
        library_id TEXT NOT NULL,
        name       TEXT NOT NULL,
        color      TEXT DEFAULT '#888888',
        created_at TEXT DEFAULT (datetime('now')), description TEXT,
        FOREIGN KEY (library_id) REFERENCES libraries(id)
    );

CREATE TABLE IF NOT EXISTS "synonyms" (
            id           TEXT PRIMARY KEY,
            library_id   TEXT NOT NULL,
            term_a       TEXT NOT NULL,
            term_b       TEXT NOT NULL,
            confidence   REAL DEFAULT 1.0,
            source       TEXT,
            is_suppressed INTEGER DEFAULT 0,
            created_at   TEXT DEFAULT (datetime('now')),
            term_a_norm  TEXT,
            term_b_norm  TEXT
        , is_suspicious INTEGER DEFAULT 0, notes TEXT);

CREATE VIRTUAL TABLE vec_annotations USING vec0(annotation_id TEXT PRIMARY KEY, embedding FLOAT[3072]);

CREATE VIRTUAL TABLE vec_passages USING vec0(
        passage_id TEXT PRIMARY KEY,
        embedding FLOAT[3072]
    );

CREATE INDEX idx_journals_abbr ON journals(abbreviation);

CREATE TABLE paper_flags (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    username TEXT NOT NULL,
    pinned INTEGER DEFAULT 0,
    key_paper INTEGER DEFAULT 0,
    followup INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id),
    UNIQUE(paper_id, username)
);

CREATE INDEX idx_paper_flags_lookup ON paper_flags(paper_id, username);

CREATE INDEX idx_paper_flags_paper ON paper_flags(paper_id);

CREATE TABLE annotation_flags (
    id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    username TEXT NOT NULL,
    key_point INTEGER DEFAULT 0,
    pinned INTEGER DEFAULT 0,
    followup INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (annotation_id) REFERENCES annotations(id),
    UNIQUE(annotation_id, username)
);

CREATE INDEX idx_annotation_flags_lookup ON annotation_flags(annotation_id, username);

CREATE INDEX idx_annotation_flags_annotation ON annotation_flags(annotation_id);

CREATE TABLE library_access (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    username TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (library_id) REFERENCES libraries(id),
    UNIQUE(library_id, username)
);

CREATE INDEX idx_library_access_user ON library_access(username);

CREATE INDEX idx_library_access_library ON library_access(library_id);

CREATE TABLE user_preferences (
    username TEXT PRIMARY KEY,
    current_library_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (current_library_id) REFERENCES libraries(id)
);

CREATE INDEX idx_passages_paper_id ON passages(paper_id);

CREATE TABLE mentions (
                id          TEXT PRIMARY KEY,
                paper_id    TEXT NOT NULL,
                annotation_id TEXT,
                mentioned_by  TEXT NOT NULL,
                mentioned_user TEXT NOT NULL,
                note        TEXT DEFAULT '',
                seen        INTEGER DEFAULT 0,
                created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE
            );

CREATE TABLE team_members (
                id         TEXT PRIMARY KEY,
                username   TEXT NOT NULL UNIQUE,
                added_by   TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

CREATE TABLE user_tag_labels (
                id         TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                label      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT '#f59e0b',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, label)
            );

CREATE TABLE paper_tags (
                id         TEXT PRIMARY KEY,
                paper_id   TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                label_id   TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP, annotation_id TEXT DEFAULT NULL,
                FOREIGN KEY(paper_id) REFERENCES papers(id) ON DELETE CASCADE,
                FOREIGN KEY(label_id) REFERENCES user_tag_labels(id) ON DELETE CASCADE,
                UNIQUE(paper_id, user_id, label_id)
            );

CREATE INDEX idx_search_id ON passages(search_id);

CREATE INDEX idx_annotations_passage_id ON annotations(passage_id);

CREATE INDEX idx_passages_id ON passages(id);

CREATE INDEX idx_papers_library_id ON papers(library_id);

CREATE INDEX idx_passages_search_id ON passages(search_id);

CREATE VIRTUAL TABLE annotations_fts USING fts5(user_note, annotation_id UNINDEXED)
/* annotations_fts(user_note,annotation_id) */;

CREATE TRIGGER passages_ai AFTER INSERT ON passages BEGIN
  INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER passages_ad AFTER DELETE ON passages BEGIN
  INSERT INTO passages_fts(passages_fts, rowid, text)
  VALUES('delete', old.rowid, old.text);
END;

CREATE TRIGGER passages_au AFTER UPDATE ON passages BEGIN
  INSERT INTO passages_fts(passages_fts, rowid, text)
  VALUES('delete', old.rowid, old.text);
  INSERT INTO passages_fts(rowid, text) VALUES (new.rowid, new.text);
END;
