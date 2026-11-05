# Changelog

## 5 November 2026: "Newest first" in the paper list

- **The paper list can be sorted newest first**, by when each paper was added to BibMan (menu next to ↻ in the Library toolbar; *A–Z by bibkey*, the order so far, is the default). It works together with search and the sidebar filters, and each browser remembers the choice. Papers imported in bulk carry the date of the import; papers with no date come last.
- Server: the paper list now includes each paper's `created_at`. Install the server before the dashboard page, since the page needs that field to sort.

## 5 November 2026: PDF hand-off address and the re-save (server only)

- **The server only remembers the published address of the web app** (`https://script.google.com/…/exec`). Apps Script tells the server where to hand over PDFs with every request; a function run from the editor (`resavePdfsCheck`, `checkPdfLinks`, …) reports the editor's `/dev` address instead, which only works for its signed-in owner. Remembering that made every PDF hand-off fail with `401 Unauthorized` until the next dashboard request. Other addresses are now ignored.
- **The re-save stops early when the web app cannot be reached:** after 5 papers in a row whose Drive check got no answer, it stops and says so at the top of its report (nothing is changed for those papers). Papers that fail for their own reason (a dead link, a PDF over 40 MB) do not count.
- **The 10-second pause now follows every paper in the re-save**, failed ones too (it was skipped after a failure).

## 3 November 2026: PDFs reach Drive again (Core 10)

- **New papers' PDFs are saved to Drive again.** The server handed them to the dashboard's web app, which runs as the person using it and refused the server (`401 Unauthorized`), so no PDF had reached Drive for a while (they still displayed, fetched from their source). Apps Script now tells the server the bookmarklet's web app instead, which runs as the owner; it saves the PDF in `BibMan_PDFs/<library>/` as before. The bookmarklet project needs the Script Property `PDF_FOLDER_ID`.
- **PDFs over 40 MB are not handed over** (Apps Script can't take much more in one request); the log names them.
- **One-time checks, run from the bookmarklet project's editor:** `checkPdfLinks` / `fixPdfLinks` (PDFs in `BibMan_PDFs` not viewable by link), and `resavePdfsCheck` / `resavePdfsStart` (papers with a PDF but no Drive copy: an existing Drive file of the same name is linked, otherwise the PDF is fetched again and saved, one paper every 10 seconds; a report is written next to the database). See MAINTENANCE.md, "PDFs in Drive".
- **Stored PDF links go through the Cloudflare Worker first** in the PDF viewer (as arXiv PDFs already did), which spares the VM's outbound data; the VM fetches the PDF only if the Worker can't.
- **The bookmarklet project now needs your approval for Drive** (it saves the PDFs as you) **and the Drive API service.** Run `authorizeDrive` once in its editor and allow the permissions; it also says whether the Drive API service is on. Until then every bookmarklet click lands on a blank Google page (`createOAuthDialog=true` in its address).
- **The bookmarklet button can no longer be dragged too early.** In **Utilities → Bookmarklet** the button used to be draggable before its code had arrived; dragging it then saved the dashboard's own page address, and clicking that bookmark opened a blank Google page (`…googleusercontent.com/userCodeAppPanel?createOAuthDialog=true#`). It now shows *Preparing bookmarklet…* (greyed out, not draggable) until the code is there, says so if it can't be prepared (click it to try again), and starts preparing as soon as the Utilities menu opens.
- Server (`bibman_e2micro_server.py`), Core 10, bookmarklet `Code.gs` and `appsscript.json` (capture version 10), dashboard (`Index.html`); the dashboard's `Code.gs` is unchanged (select Core 10, version 14).

## 2 November 2026: an access code instead of the access sheet (Core 9)

- **No list of people any more.** The dashboard is open to anyone signed in to Google who has its link and the group's **access code** (Script Property `BIBMAN_ACCESS_CODE` in the Frontend project); the `allowed_users` sheet is no longer read. Each person types the code once (or it is in the link as `?access=CODE`) and BibMan remembers it for them, as a fingerprint, not the code itself, until the code is changed; then everyone is asked once for the new one. Every dashboard action checks the current code, so a change takes effect at once. Capitals count; spaces at either end are ignored; with no code set, nobody gets in.
- **Admins are listed in the Script Property `ADMIN_EMAILS`** (emails separated by commas) instead of the sheet's admin column.
- **Core members, listed in `CORE_MEMBERS`, never need the access code**, and neither do admins: they are let in by their Google email. Changing the code doesn't affect them.
- The bookmarklet and gooTeX are unchanged: the bookmarklet uses `GAS_CREDENTIAL`, gooTeX its read-only `EXPORT_CREDENTIAL`.
- **The dashboard no longer asks for Google Sheets permission** (Frontend 13): it was needed only to read the access sheet.
- Core library 9 and a new Frontend `Code.gs` (12), which must be installed together; Capture: select Core 9 and redeploy (its `Code.gs` is unchanged). A Frontend still on the old `Code.gs` with Core 9 lets nobody in and says it needs updating. No server or dashboard (`Index.html`) change.

## 2 November 2026: the same label on several notes of a paper

- **Fixed: a label could be used only once per paper.** Databases made before note tagging had the rule "one person, one label, once per paper", counting the paper and all its notes together, so tagging a second highlight with a label already on another note (or on the paper) was silently ignored: the tick showed, then was gone. The rule is now once per person on the paper as a whole and once on each note. `cloud/bibman_fix_tags.py` changes it on an existing database, keeping every tag and the old table (`paper_tags_old_rule_<date>`) as a backup; the server also changes it at start if it finds the old rule, and `cloud/schema.sql` has the new one. The server now answers "already there" instead of pretending to add a tag that is already there.
- **Deleting a note removes its tags and @mentions** (they were left behind, pointing at a note that no longer existed, making the *In notes* counts too high and letting the paper match a tag filter); deleting a paper removes its mentions too. The repair script removes those already left behind, after writing them to a backup TSV, and the nightly processing removes any that appear later.
- Server (`bibman_e2micro_server.py`) and a one-time script; no dashboard or Apps Script change.

## 1 November 2026: highlighting and tagging made clearer and safer

- **Press H to highlight** the text selected in a PDF (it was Alt+A, "annotate", which also never worked on a Mac). H only acts while text is selected in the PDF and you are not typing in a box, and as a plain letter it clashes with no browser shortcut on Windows or Mac. The box that opens is titled *Highlight this passage*: an optional note and **Save highlight** (the button was called *Bookmark*). It says that, once saved, the highlight is tagged (🏷) or marked 🎯 Key Point, 📌 Pinned or 🔄 Follow-up with the buttons on its note in the Annotations list. (Tags are not offered in the box itself: the list of labels could get long, and the marks are not labels.)
- **Tag pickers only add and remove tags.** The pickers behind 🏷 Tag (whole paper) and a note's 🏷 say what the ticks mean ("✓ = already on this paper: click it to take it off, only here") and no longer offer rename, share/private or delete, which change a label everywhere. Those stay in the Tags list in the left sidebar, so a slip while untagging one note can't delete a label from the whole library.
- **Deleting a label everywhere needs its name typed.** The ✕ in the sidebar Tags list opens a box saying the label will be taken off every paper and every note that has it, in all libraries, and can't be undone; *Delete everywhere* only works once the label's name has been typed (capitals and spaces at the ends don't matter). The hover text on ✎ and ✕ there now says they act everywhere.
- **Paper tags and note tags shown apart.** The tag strip above the annotations in paper view has two lines: *Paper:* for tags on the paper as a whole, and *In notes:* for tags on highlights and notes, each label once with the number of notes that have it (e.g. *TCAN26 ×2*). Hovering shows who applied it.
- **The ✕ on a note says what it deletes:** *Delete this highlight and its note*, or *Delete this paper note* (it said only *Delete*), and so does the question before deleting.
- **Brighter counts in the left sidebar** (All Papers, Key Paper, Notes, Highlights, Pinned, Follow-up): they were nearly the colour of the background; now the same colour as their label, brightening with it on hover and turning blue with it when selected.
- **Key Paper is marked when selected** in the left sidebar, like the other filters (it filtered correctly but its row never turned blue).
- **Fixed: clicking elsewhere while a highlight was saving** gave an error ("Cannot read properties of null"): the highlight was saved but did not appear in the list until the page was reloaded. The save now keeps its own copy of the selected text and paper.
- **Tag pickers respond at once.** Clicking a label ticks or unticks it immediately (dimmed until saved) and the picker stays open, so several labels can be picked in a row; before, nothing visible happened until it closed by itself. If a save fails, the tick goes back and a message says why. The library list and tag strip refresh once, just after the last click.
- Dashboard only (`Index.html`): no server or Apps Script change.

## 1 November 2026: search indexes kept up to date every night

- **New papers reach meaning-based search the morning after they are added.** After the nightly processing has embedded new passages, the server starts `bibman_rebuild_usearch.py --sync`, which brings each library's index up to date: it adds passages that are new, re-extracted or moved in (in random order) and removes those deleted, replaced or moved out, so each index holds exactly its library's embedded passages. It is checked before it replaces the index (the passages it added plus 50 already there must come back within the first 10, at least 97% of them), keeps the previous index as `.prev`, and keeps a result that fails as `.failed`. Log: `bibman_usearch_sync.log` next to the database.
- **No restart after a rebuild, sync or rollback:** the server checks the index list before each meaning-based search and loads changed indexes by itself.
- Only one rebuild or sync runs at a time (a lock file next to the database).
- Each index keeps a small list of its passage IDs (`.keys.npy`), so a sync with nothing to do finishes in minutes without loading the index. The sync log shows how long each stage took.
- A full rebuild is now an occasional tidy-up (every few months) rather than a monthly chore.

## 31 October 2026: meaning-based search per library; no leftover embeddings

- **Meaning-based search stays in the current library.** Each library now has its own search index (`bibman_768_i8.lib-<library id>.usearch`, listed in `bibman_768_i8.libraries.json`), and a search looks only at the current library's. Before, there was one index for all libraries: its nearest matches could come from any library, so other libraries' papers showed up in results and took up places a relevant passage of this library could have had. Keyword and note searches were already limited to the library.
- **`bibman_rebuild_usearch.py` builds one index per library**, all of them or only those named with `--library NAME`. A small library rebuilds in seconds, so after moving papers you can bring it up to date at once. Each library keeps its previous index as `.prev`; `--rollback --library NAME` swaps it back.
- **Passages are added to an index in random order**, shuffled across the library: added paper by paper, the index found passages less reliably among each paper's very similar passages. **A better check** before a new index is installed (300 passages spread across the library; at least 97% must come back within the first 10), and a new index that fails it is kept as `.failed` (`--recheck --library NAME` checks it again and installs it if it passes).
- A paper moved to another library drops out of its old library's meaning-based results at once (each hit is checked), and joins the new library's at that library's next rebuild. A library without an index yet is compared directly against its own embeddings, up to 20,000 passages.
- **No more leftover embeddings.** Embeddings are saved only for passages and notes that still exist (a paper re-extracted while the nightly job was embedding it used to leave embeddings for passages that no longer existed), deleting a paper or library now also removes its notes' keyword and embedding entries, and failures to remove embeddings are logged instead of being silently ignored. As a safety net, the nightly job removes any embedding whose passage or note no longer exists and logs how many.
- Meaning-based hits are mapped back to passages with two indexed lookups, not a join: without table statistics SQLite answered the join by reading every passage of the library, which made searches time out.
- **Fixed:** the list of notes still missing an embedding (`/api/backfill/annotations`) failed with an error.
- Server only: no Apps Script versions change.

## 29 October 2026: version number in code, search limit in one place

- **The Core library's version number is now in its code** (`BIBMAN_CORE_LIBRARY_VERSION` in `Code.gs`) instead of a Script Property. Script Properties are not saved with a library version, so every web app reported the newest Core even while running an older one, and the "update Core" banner could not catch a web app that had not been switched over.
- **The Venn Search time limit is set in one place** (`VENN_JOB_MAX_SECONDS` on the server). The server sends it with each search, and the dashboard's "Still searching… up to 2 minutes" message, its own give-up point and the server's timeout message are all worded from it. The limit stays at 2 minutes.
- **Capture web app update notes:** its update information carried the version number where the "what changed" text belonged.
- Versions: Core library 8, Frontend web app 11, Capture web app 7.

## 29 October 2026: shared and private tag labels

- **Tag labels are shared by default.** Every label appears for everyone (sidebar, tag picker, Venn filters), with Just me on or off, and anyone can use it, so a group can tag papers and notes with one label (for example, a project name). Who tagged what stays personal: **Just me** filters by your own tagging, **Everyone** by anyone's, and removing a tag removes only yours.
- **Private labels** (tick *Private (only you)* when creating, or switch later with 👥 / 🔒): only you see and use them, in every view. Notes tagged with them stay visible as usual; only the tag is hidden.
- Only a label's creator can rename, recolor, delete or switch it. Deleting it, or making it private, is refused once others have used it. Duplicate names are refused (capitals ignored). The limit stays at 8 labels per person.
- **Creating a label from a 🏷 button also applies it** to that note or paper. Before, it only created the label, and the picker then reopened for the whole paper.
- **Manage your labels from the sidebar:** hover over one of your labels in the Tags list for 👥/🔒 (shared or private), ✎ (rename) and ✕ (delete).
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
