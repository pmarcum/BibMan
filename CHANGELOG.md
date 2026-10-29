# Changelog

## 29 October 2026: shared and private tag labels

- **Tag labels are shared by default.** Every label appears for everyone (sidebar, tag picker, Venn filters), with Just me on or off, and anyone can use it, so a group can tag papers and notes with one label (for example, a project name). Who tagged what stays personal: **Just me** filters by your own tagging, **Everyone** by anyone's, and removing a tag removes only yours.
- **Private labels** (tick *Private (only you)* when creating, or switch later with 👥 / 🔒): only you see and use them, in every view. Notes tagged with them stay visible as usual; only the tag is hidden.
- Only a label's creator can rename, recolor, delete or switch it. Deleting it, or making it private, is refused once others have used it. Duplicate names are refused (capitals ignored). The limit stays at 8 labels per person.
- **Creating a label from a 🏷 button also applies it** to that note or paper. Before, it only created the label, and the picker then reopened for the whole paper.
- Existing labels became shared.
- Versions: Core library 7, Frontend web app 10, Capture web app 6.

## 29 October 2026: dashboard test pages

- **Try a new dashboard page before it goes live:** `?branch=NAME` on the dashboard address loads `Index.html` from that branch; the normal address keeps loading `main` (Core 6, Frontend 9, Capture 5).
- **Personal-marks display is live:** your marks filled, others' faint; dashed Paper View buttons for marks made only by others; "by @name" on other people's notes. As first written, this page stopped the dashboard from loading through Google's page delivery (even a single extra comment line in the paper-list code was enough); it was narrowed down with test pages and shipped once the exact page loaded.

## 29 October 2026: personal Key paper / Pinned / Follow-up marks

- **Marks are personal, like tags.** Each person has their own Key paper, Pinned and Follow-up marks, on papers and on notes. **Just me** shows yours; **Everyone** shows everyone's, with yours filled and others' faint. Clearing your mark never touches anyone else's.
- **Marks on notes now count for the paper.** A paper appears under Key paper / Pinned / Follow-up (list icon, counts, filters) when the paper or one of its notes carries that mark. Before, marks on notes were ignored there.
- **Marking a colleague's note adopts it:** with **Just me** on, you see it alongside your own notes (labelled with its author), and it counts for your note icons and searches.
- Existing marks were copied to their owner by `cloud/bibman_personal_marks.py`; the old shared columns are kept as a backup.
- **Venn Search finds words that appear only in notes.** A search whose words matched notes but no paper text used to return nothing.

## 29 October 2026: much faster Venn Search

- **Large Venn Searches are several times faster** (for example, "galaxy" + "hot gas": about 4 minutes before, about 1 minute after, from a cold start). The step that decides each result's "~ synonym" / "~ semantic" badge, and the exclude step, asked the database "which of these results contain this word?" in a form that made it read every passage in the library containing the word (minutes on a standard disk). They now read only the keyword index and compare in memory. Results are unchanged (checked old against new on a test library). Cost: a few tens of MB of memory during a large search.
- **Timed-out and cancelled searches stop on the server** instead of running on in the background (Core 5).
- Versions: Core library 5, Frontend web app 8, Capture web app 4.

## 28 October 2026: Venn Search through Apps Script

- **Venn Search works from networks that block the server's address.** Some workplace and campus networks block dynamic-DNS names such as `*.duckdns.org`, so the dashboard's one direct browser-to-server request, Venn Search, failed there with "Failed to fetch". It now goes through Apps Script like every other dashboard action (Core 4). Because Apps Script allows only about a minute per request and large searches can take longer, the server runs each search as a background job and the dashboard checks back for the result ("Still searching"). Limit: 2 minutes per search.
- **The Gemini key and the server's address are no longer sent to browsers.** Apps Script adds the key when it calls the server.
- **Venn Search passes the access-list check** like every other dashboard call.
- **Clear warning when meaning-based search fails.** If Google refuses the Gemini key (for example, prepaid credit used up), rate-limits it, or doesn't answer in time, the dashboard now says so in a red notice instead of silently showing keyword results only.
- Versions: Core library 4, Frontend web app 7, Capture web app 3 (both web apps redeployed on Core 4; their code is unchanged).

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
