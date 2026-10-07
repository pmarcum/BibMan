# Changelog

## October 2026: packaging for public release, review fixes

The code was reviewed independently (security, correctness, and coexistence with gooTeX). These changes came out of that review and are deployed on the reference server.

**Search**
- **Keyword search no longer fails on astronomy notation.** Synonyms such as `C+`, `S/N` or `M*` used to break the whole keyword query, or flood it. Every term is now quoted, and synonyms that full-text search would reduce to one or two letters are skipped.
- **Highlights show what was actually searched**, the phrase and its synonyms, instead of loose single letters.
- **New passages get their semantic-search key (`search_id`) when saved.** Previously, passages added after April 2026 never entered the semantic index.
- **Current Gemini text model.** Google shut down `gemini-2.0-flash` on 1 June 2026. The server's fallback is now `models/gemini-3.5-flash-lite`, and the guides say to set `GENERATE_MODEL` explicitly.
- **Narrower database trigger.** `passages_au` now fires only when a passage's text changes, so other updates never touch the keyword index. New installs get it from `schema.sql`; existing ones get it from the backfill script.
- **New tools in `cloud/`:**
  - `bibman_search_check.py`: read-only health check.
  - `bibman_backfill_search_ids.py`: fills in missing keys, with a self-verifying formula check and a dry run by default.
  - `bibman_rebuild_usearch.py`, rewritten:
    - writes the index where the server reads it;
    - keeps the previous index (and refuses to overwrite that backup) with a one-command `--rollback`;
    - checks the new index (key lookups, self-searches) before installing it;
    - checks the new index (key lookups, self-searches) before installing it;
    - records the compression method so queries are compressed the same way.

**Fixes**
- **Note editing works.** It previously failed with a server error.
- **The nightly synonym step works.** It previously failed outside a web request.

**Security**
- **No public bibliography download.** `/bibman/get_bib`, which needs no credential, is blocked at nginx.
- **The access list is checked on every dashboard call** (Core library v3), not only when the page loads.
- **gooTeX gets a read-only `EXPORT_CREDENTIAL`.** It works only on the three bibliography-export routes, so gooTeX no longer needs the full-access `GAS_CREDENTIAL`.
- **The server refuses to start without a strong `GAS_CREDENTIAL`.** Credentials are compared in constant time.
- **The Gemini API key is sent in a header**, never in a URL, so it no longer appears in logs or error messages.
- **The PDF-proxy Worker in the repo** accepts any site, but requires a secret key and passes on only real PDF files.

**Docs**
- **New guides:** README (users), DEPLOY.md (new groups) and MAINTENANCE.md (hosts), including adding, removing and fully cutting off a user.
- **Sheets-era files** moved to `legacy/sheets-version/`.
