# Maintaining a BibMan server

For whoever hosts a BibMan instance. Setup is in [DEPLOY.md](DEPLOY.md). This page covers keeping it running, updating it, and recovering it.

## Where things live on the VM

| Path | What it is |
|---|---|
| `/home/bibman/bibman/` | Server code (`bibman_e2micro_server.py`, `bibman_cron.py`, `bibman_rebuild_usearch.py`) and its `venv/` |
| `/home/bibman/bibman.db` | The SQLite database: every library, paper, passage, annotation, tag, and the 3072-dim Gemini embeddings (`vec_passages`, `vec_annotations`). **This is the data. It is not in git.** |
| `/home/bibman/bibman_768_i8.lib-<library id>.usearch` | Semantic-search indexes, one per library, loaded when the service starts and listed in `bibman_768_i8.libraries.json`. Can always be rebuilt from the database. (`bibman_768_i8.usearch`, the shared index used before 31 Oct 2026, is no longer read and can be deleted.) |
| `/home/bibman/bibman_config.json` | Small runtime settings the server writes itself (current library, last-seen Apps Script URL). |
| `/etc/systemd/system/bibman.service` | Service definition, including `SESSION_SECRET` and `GAS_CREDENTIAL`. |
| `/etc/systemd/system/bibman.service.d/export-credential.conf` | Optional: the read-only `EXPORT_CREDENTIAL` for gooTeX. |
| `/etc/nginx/sites-available/proxy-router` | HTTPS front door; routes `/bibman/` to port 8081 (and `/gootex/` to 8082 if present). |

The database path comes from `DB_PATH` in the service file; the index and config file always sit in the same folder as the database.

## Day to day

```bash
sudo systemctl status bibman                 # running?
sudo journalctl -u bibman -n 100 --no-pager  # recent log
sudo journalctl -u bibman -f                 # follow the log live
sudo systemctl restart bibman                # restart (takes a few seconds; reloads the indexes)
curl -s https://YOUR-SUBDOMAIN.duckdns.org/health
```

## Scheduled jobs

| Job | Runs from | When | What it does |
|---|---|---|---|
| Nightly processing (`runNightlyCron`) | Apps Script time trigger in the **Frontend** project (created once by `setupCronTrigger`) | Daily, about 5 am Pacific | Calls `POST /api/cron/run` with the Gemini key; the server then embeds new passages, generates synonym pairs, and removes embeddings left behind by deleted passages or notes and tags and @mentions left behind by deleted notes or papers, in the background, in small batches, and finally starts the **search-index sync** (below) |
| Search-index sync (`bibman_rebuild_usearch.py --sync`) | Started by the nightly processing, as a separate low-priority process | Daily, right after the nightly processing | Brings each library's index up to date: adds passages that are new or moved in, removes deleted or moved-out ones. Log: `/home/bibman/bibman_usearch_sync.log` |
| Search-index rebuild | **Not scheduled**: run by hand (see "The semantic-search index") | Every few months, or if a sync keeps failing its check | Rebuilds the usearch files (one per library) from the stored embeddings, from scratch |

**Why the nightly job runs from Apps Script and not from the VM's crontab:** the VM never stores the Gemini key. Each user's key lives only in Script Properties and is sent with each request, so a job on the VM would have no key to use. The Apps Script trigger supplies it each night. This also means a compromised VM exposes no Gemini key at rest. (The old crontab lines, and those in `bibman_cron.py`'s docstring, are disabled and superseded.)

**Why the index rebuild isn't scheduled:** on an e2-micro a large library is slow and heavy to rebuild (about 4 hours for ~390,000 passages, because the e2-micro is held to about a quarter of a CPU for sustained work; a few hundred MB of memory), and it should run when nobody is using BibMan or gooTeX. A person should watch it and check the result. The nightly sync keeps the indexes current in between, so a full rebuild is only an occasional tidy-up (removed passages leave small gaps in an index's web of neighbours, which a fresh build closes).

BibMan needs no crontab entries on the VM. If gooTeX shares the VM, its own monthly cache cleanup is in the `bibman` user's crontab; leave that alone.

To check the nightly trigger: open the Frontend project → **Triggers** (clock icon) → `runNightlyCron`. Its executions log (**Executions**, the list icon) shows whether each night's run succeeded.

## How the dashboard reaches the server

Every dashboard action, including Venn Search (since Core 4), goes from the browser to Apps Script, and Apps Script calls the VM server-to-server. Browsers never connect to the VM's address directly. This matters because many workplace and campus networks block dynamic-DNS names such as `*.duckdns.org` (their DNS sends the name to a dead-end address), which breaks any feature that needs a direct browser connection. The exceptions are PDF display: Drive copies are fetched by the browser from Google Drive, and arXiv PDFs (and, since Core 10, other stored PDF links, with the VM as the fallback) through the Cloudflare Worker.

A request through Apps Script must finish within about a minute, but a large Venn Search can take longer on an e2-micro. So Venn Search runs as a background job on the server (`/api/search/venn/start`, then `/api/search/venn/result/<id>`): Apps Script starts it and waits up to 5 seconds; if it isn't finished, the dashboard shows "Still searching" and keeps asking, up to 40 seconds per request. Agreed limits:
- **2 minutes per search** (`VENN_JOB_MAX_SECONDS` in the server). After that the search is stopped on the server (its database work is interrupted) and the dashboard reports a timeout. If searches time out, try fewer or more specific terms, or a lower **Max results**.
- **Cancel** stops the search on the server too, once it has been running for about 5 seconds (before that, the 2-minute stop applies).
- To change the limit, change only `VENN_JOB_MAX_SECONDS`. The server sends it with each search (`max_seconds`), and every message ("Still searching… up to 2 minutes", the timeout message) is worded from it.
- Finished results are kept in the server's memory for 10 minutes (`VENN_JOB_KEEP_SECONDS`), then deleted.
- A restart of BibMan loses searches that were running; run them again.
- The dashboard itself gives up one minute after the limit without an answer (3 minutes today; only if the server stops responding).

## Personal marks (Key paper, Pinned, Follow-up)

Since 29 October 2026 these marks are personal, like tags. Each person's marks on a paper are a row in `paper_flags` (paper + person), and marks on a note or highlight are a row in `annotation_flags` (note + person). Anyone may mark any note they can see, and their mark is their own.
- **Just me** shows only your marks; **Everyone** shows everyone's. In Everyone view, your marks look filled, and marks made only by others look faint (in the paper list) or have a dashed outline (Paper View buttons). Clicking always sets or clears **your** mark; other people's are never changed.
- A paper counts as Key paper / Pinned / Follow-up in the paper list, its counts and the filters if the paper **or one of its notes** carries that mark.
- **Marking someone else's note adopts it.** In **Just me** you see the notes you wrote **and** notes by others that you have marked (any of the three marks): in Paper View (labelled "by @author"), in the paper list's note icon and counts, in Venn Search and in your annotated papers. Clearing your last mark on it un-adopts it.
- The old shared columns (`papers.key_paper`, `pinned`, `followup`; `annotations.flag_key_point`, `flag_pinned`, `flag_follow_up`) are no longer read or written. They keep the state from before the switch as a backup. `cloud/bibman_personal_marks.py` copied that state into the new tables (dry run by default, `--apply` to write, `--user` names who receives the existing paper marks).

## Tags: shared and private labels

Since 29 October 2026, tag labels (`user_tag_labels`) are **shared** by default. Who tagged what stays personal (`paper_tags` records the person).
- **A shared label** appears for everyone (sidebar, tag picker, Venn filters), whether Just me is on or off, and anyone can apply it to papers and notes. **Just me** filters by your own tagging; **Everyone** by anyone's. Removing a tag removes only yours.
- **A private label** (`is_private = 1`, 🔒) is seen and applied only by its creator, in every view including Everyone. Notes tagged with it stay visible to others as usual; only the tag is hidden. Private means hidden in BibMan's screens: a server administrator can still read it in the database.
- New labels are shared unless *Private (only you)* is ticked. The creator can switch a label later (👥 / 🔒 in the Tags list in the left sidebar). Making it private is refused if others have used it.
- Only the creator can rename or delete a label, in the Tags list in the left sidebar (the tag pickers only add and remove tags). Deleting asks for the label's name to be typed, and is refused if others have used it (the message names who, and on how many papers).
- Each person can put a label once on a paper as a whole and once on each of its notes (unique index `ux_paper_tags_place`). Databases made before 2 November 2026 allowed it only once per paper, paper and notes together, and silently ignored further uses; `cloud/bibman_fix_tags.py` (dry run by default, `--apply`) changes the rule, and the server does the same at start if it finds the old one. Either keeps the old table as `paper_tags_old_rule_<date>`: drop it a week or so later, once all is well (`DROP TABLE paper_tags_old_rule_...;`).
- Deleting a note removes its tags and @mentions; deleting a paper, those of the paper and its notes.
- At most 8 labels per person (shared and private together). A new or renamed label may not have the same name, ignoring capitals, as a label you can already see. A colleague can still create a shared label with the same name as your private one, since they can't see it.
- Labels are not tied to a library: a label shows in every library.
- Labels that existed before the change became shared (the `is_private` column is added at server start, defaulting to 0).

## Gemini billing (Prepay)

Gemini API accounts created since March 2026 default to Google's **Prepay** plan: you buy credit in advance in AI Studio (ai.studio/projects → your project → Billing), and usage is deducted from it. **When the balance reaches $0, every key on that billing account stops working at once**, with HTTP 402 ("Your prepayment credits are depleted"). Venn Search then falls back to keyword-only results and (since 28 October 2026) shows a red warning saying why, and the nightly embeddings and synonym suggestions fail until credit is added. Nothing is lost; the nightly job catches up once the key works again.

- Check the balance in AI Studio now and then. BibMan's usage is small (cents per month for one group).
- To confirm a key works from the VM without saving it anywhere:
```
read -rs -p "Paste Gemini key (hidden): " K; echo; curl -s -X POST -H "x-goog-api-key: $K" -H "Content-Type: application/json" -d '{"content":{"parts":[{"text":"test"}]}}' https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent | head -c 700; echo; unset K
```
  A working key returns `{"embedding": {"values": [...`; otherwise Google's error message says why.
- The alternative is the free tier (a key in a project with no billing). It costs nothing but has rate limits, and Google may use the content sent (search phrases, passage and note text) to improve its products.

## The semantic-search index

**How it works**
- **Embeddings:** Gemini returns 3072-dimensional embeddings, and they are stored at full size in the database.
- **The indexes:** for speed and to fit in 1 GB of RAM, meaning-based search uses a separate **usearch** index for each library, and a search looks only at the current library's index (so other libraries' passages can never take up its places). Each holds the first 768 dimensions of each embedding (Gemini embeddings are designed to be truncated this way), compressed to int8. For a large library it is a few hundred MB; a small one, well under 1 MB. Never build it as float16 or at more dimensions on an e2-micro: it will not fit in memory.
- **Keys:** index keys are each passage's `search_id`, a 60-bit number taken from the first 15 hex digits of the passage's UUID: `int(uuid.replace('-', '')[:15], 16)` (the rule the April 2026 migration used). **Why 15 digits, not 16:** SQLite stores integers as *signed* 64-bit numbers (largest 2^63 − 1). Sixteen hex digits make a 64-bit number, which is too big for about half of all UUIDs, and the April migration failed on them; fifteen digits (60 bits) always fit. (usearch itself accepts any unsigned 64-bit key, so it is not the limit.) **Uniqueness:** in a random (version 4) UUID the 13th hex digit is always `4`, so those 15 digits carry 56 random bits, about 7×10^16 possible IDs. The chance of any two passages sharing an ID is about n²/(2×2^56): roughly 1 in a million at 390,000 passages, and still under 1 in 1,000 at 10 million passages (about 25 times this library). A shared ID can't detach notes or tags, which are linked by UUID; at worst one meaning-search hit would show the wrong passage. `bibman_backfill_search_ids.py` refuses to write any ID that would collide. **Never change this rule:** every existing ID and the index keys depend on it. Search results are mapped back to passages through that column. The server sets it for every new passage (since 6 Oct 2026). Before that, passages added after the April 2026 migration got none.
- **The list file:** `bibman_768_i8.libraries.json`, written by the rebuild script, records each library's index file, its number of vectors, when it was built, and its compression method (how vectors were compressed to int8; the server compresses search queries the same way). Files are named by the library's ID, so renaming a library changes nothing.
- **A library without an index yet** (for example one created after the last rebuild) is compared directly against its own stored embeddings, which is exact. This gets slower as a library grows, so above 20,000 passages (`DIRECT_SEARCH_MAX_PASSAGES` in the server) it is not tried: the dashboard says meaning-based search is unavailable and the library needs a rebuild.
- **Leftover embeddings:** a passage or note that is deleted, or replaced when a paper is re-extracted, has its embedding removed with it, and embeddings are only saved for passages and notes that still exist. As a safety net the nightly job also removes any embedding whose passage or note no longer exists, and logs how many (`removed leftover embeddings: …`). That count should normally be 0; if it keeps growing, something is leaving them behind.

**The indexes are updated nightly.** New papers are found by word and synonym search straight away, and by meaning-based search the morning after they are embedded: the nightly processing embeds their passages, then starts the sync, which adds them to their library's index (and removes passages that were deleted, re-extracted or moved out). A paper moved to another library drops out of its old library's meaning-based results at once, and joins the new library's after the next sync. BibMan loads changed indexes by itself before the next search; no restart is needed.
- **The sync** loads a library's index into memory to change it (about 420 MB for a 390,000-passage library, as much as a rebuild), adds and removes passages, and checks the result before it replaces the index: the passages it added (up to 300) plus 50 already in the index must each be present, at least 97% of them coming back within the first 10. It keeps the previous index as `.prev` (replaced at each sync); a result that fails the check is kept as `.failed`, the current index stays in use, and the log says why. Each index has a small list of its passage IDs next to it (`bibman_768_i8.lib-<library id>.keys.npy`, about 3 MB for 390,000 passages), so on a night with nothing new the sync sees that within minutes without loading the index; only when there are changes does it load, change and save the index file. The log shows how long each stage took. Only one sync or rebuild runs at a time.
- **Check the sync now and then:** `tail -20 /home/bibman/bibman_usearch_sync.log`. Each night it lists, per library, `already up to date` or `synced: N added, M removed … check passed`. If a library's sync fails night after night, run a full rebuild of that library.

**Scripts** (in `cloud/`, installed in `/home/bibman/bibman/`; all run as `bibman` with BibMan's Python):

| Script | What it does | Changes anything? |
|---|---|---|
| `bibman_search_check.py` | Counts passages missing a search ID, verifies the ID formula against existing IDs, identifies how the live index was built, measures search accuracy on a sample, and reports disk and memory. | No (read-only) |
| `bibman_backfill_search_ids.py` | Fills in missing search IDs. Dry run by default; `--apply` writes. It refuses to write unless the formula reproduces every existing ID and no new ID collides. | Only with `--apply`, and only rows that have no ID |
| `bibman_rebuild_usearch.py` | Rebuilds the indexes from stored embeddings (no Gemini calls): every library, or only those named with `--library NAME`. For each library it adds the passages in random order (see below), writes to a temporary file, checks it, keeps the current index as its `.prev`, then installs the new one and updates the list file. A new index that fails its check is kept as `.failed`. BibMan picks up new indexes by itself. `--sync` updates the existing indexes instead of rebuilding them. | The index files and the list file only (plus temporary files it removes); the database is opened read-only |

**Rebuilding.** For a large library, do this when nobody is using BibMan **or gooTeX**. Libraries are built one at a time (small ones first, in seconds), so peak memory is set by the largest: about 420 MB for a 390,000-passage library. `nice` lowers its CPU priority but not its memory use. A small library alone (`--library Satellites`) takes seconds and can be rebuilt any time.

1. **Back up first:** take a snapshot of the VM's disk (Compute Engine → Disks → the VM's disk → *Create snapshot*). It costs cents and covers everything, including the database.
2. **Run the scripts:**
```
cd /home/bibman/bibman
sudo -u bibman venv/bin/python bibman_backfill_search_ids.py            # dry run: how many IDs are missing
sudo -u bibman venv/bin/python bibman_backfill_search_ids.py --apply    # only if the dry run said OK
sudo -u bibman venv/bin/python bibman_rebuild_usearch.py --dry-run      # lists each library's passages and any .prev backups
# about 4 hours for ~390,000 passages on an e2-micro; runs in the background, so a dropped SSH session doesn't stop it
sudo -u bibman nohup nice -n 19 venv/bin/python bibman_rebuild_usearch.py > ~/rebuild.log 2>&1 &
# (or only one library:  sudo -u bibman venv/bin/python bibman_rebuild_usearch.py --library Satellites)
tail -f ~/rebuild.log                          # watch progress (Ctrl+C stops watching, not the rebuild); wait for "finished"
# BibMan loads the new index by itself before the next search; the log then shows it:
sudo journalctl -u bibman -n 12 --no-pager    # expect "USearch index loaded for <library>: N vectors, method C" per library
```
3. **How a new index is checked:** it must hold every passage, and of 300 passages chosen at random across the library, each must be present and at least 97% must come back within the first 10 when searched with their own meaning, at the server's search settings (the October 2026 Extragalactic index scored 99%). The result line shows all the figures. If the check fails, the library keeps its current index and the new one is kept as `bibman_768_i8.lib-<library id>.usearch.failed`; `--recheck --library NAME` checks it again and installs it if it passes, so a long rebuild is never thrown away.
4. **Why passages are added in random order:** added one paper after another, as in the first per-library build (31 Oct 2026), the index finds passages noticeably less reliably among a paper's very similar passages (that build failed its check). So the script reads the library once into temporary files next to the database (about 300 MB for 390,000 passages), then adds the passages shuffled across the whole library. The shuffle uses a fixed seed, so the same data gives the same index. The temporary files are removed afterwards.
5. **About the old indexes:** the rebuild keeps each library's current index as its `.prev` and **refuses to overwrite** an existing `.prev` (it checks every library before building anything). For later routine rebuilds, once you're happy with the current indexes, add `--replace-prev` (or delete the old `.prev` files yourself).
6. **About the fill-in:** `bibman_backfill_search_ids.py` also narrows the database trigger `passages_au` so it fires only when a passage's *text* changes. Before, setting an ID would also rewrite that passage's keyword-index entry. New installations get the narrowed trigger from `schema.sql`.

**To go back to the previous index:**
```
sudo -u bibman /home/bibman/bibman/venv/bin/python /home/bibman/bibman/bibman_rebuild_usearch.py --rollback --library Extragalactic
```
This swaps that library's index with its `.prev` (and its entry in the list file); BibMan picks it up before the next search. Running it again swaps them back. (The next nightly sync then brings the restored index up to date.)

Never run the old one-off `reindex_i8.py`: it overwrites the index file that the running server has open.

## Updating the server code

**This repo is the source of truth.** To deploy a change:

```bash
sudo -iu bibman
cd ~/BibMan-repo && git pull
cp ~/bibman/bibman_e2micro_server.py ~/bibman/bibman_e2micro_server.py.bak_$(date +%Y%m%d)
cp cloud/bibman_e2micro_server.py ~/bibman/
exit
sudo systemctl restart bibman && sudo journalctl -u bibman -n 30 --no-pager
```

If something breaks, copy the `.bak_` file back and restart. To confirm the VM is running exactly what the repo holds, compare checksums: `sha256sum /home/bibman/bibman/bibman_e2micro_server.py` against `sha256sum cloud/bibman_e2micro_server.py` in a fresh clone.

Newer tables and columns are added by the server itself whenever it opens the database (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN`), so ordinary updates need no manual database migration. If you change the schema, also update `cloud/schema.sql` so new instances start with it: `sqlite3 -readonly bibman.db .schema` prints the current definitions (remove the FTS/vec0 shadow tables, as the header of `schema.sql` explains).

## Updating the Apps Script side, and `version.json`

Every deployed instance compares its own version numbers with [`version.json`](version.json) on `main` and shows an "update available" banner in the dashboard when it is behind. The Core library's number is **in its code** (since Core 8); the two web apps' numbers are **Script Properties**:

| Component | Where the number is set | `version.json` key |
|---|---|---|
| Core library | `const BIBMAN_CORE_LIBRARY_VERSION = …;` near the top of the Core `Code.gs` | `bibman_core_library_version` |
| Frontend web app | `FRONTEND_THINCLIENT_VERSION` | `bibman_frontend_thinclient_webapp_version` |
| Capture web app | `BOOKMARKLET_CAPTURE_VERSION` | `bibman_bookmarklet_capture_webapp_version` |

**Why the Core number is in the code:** Script Properties are not saved with a library version. With the number in a property, every web app reported the newest Core number even while still running an older Core, so the "update Core" banner could never catch a web app that was not switched over. A number in the code is saved with each version, so each web app reports the Core it really uses. (The old Script Property `BIBMAN_CORE_LIBRARY_VERSION` is no longer read and can be deleted.) The web apps don't have this problem: each reads its own property from its own live code.

**Numbering rule (keep it simple):** release numbers *are* the host's Apps Script deployment numbers. On the host instance, each project's number (Core: in `Code.gs`; web apps: Script Property) equals the number shown under **Deploy → Manage deployments** for that project, and `version.json` carries the same numbers. On another group's instance the number records which release they installed, which need not equal their own deployment count.

Current versions (29 October 2026): Core library **8** (version number in code; shared and private tag labels; test pages; Venn Search through Apps Script, cancellable; no Gemini key or server address in the browser), Frontend web app **11**, Capture web app **7**. Both web apps select Core version **8** under **Libraries**.

To release a change:
1. Update the files in `apps_script/`, paste them into the project (for a Core change, first set `BIBMAN_CORE_LIBRARY_VERSION` in `Code.gs` to the number the new deployment will get), and deploy with **Deploy → Manage deployments → Edit (pencil) → Version: New version → Deploy** (this keeps the web-app URLs, so bookmarklets keep working).
   If the new code needs access the project didn't have before (for example Drive), run a function in that project's editor once and allow the permissions; until then the web app answers every request with a blank Google page whose address contains `createOAuthDialog=true` (a bookmarklet click just lands on that page). In the bookmarklet project, run `authorizeDrive`.
2. For a Core change: in **each** web app, open **Libraries → BibManCore**, select the new Core version, then redeploy that web app the same way. A web app's live deployment is a snapshot: changing the library setting in the editor has no effect until the web app is redeployed.
3. Set each changed web app's Script Property to its new deployment number (the Core number is already in its code).
4. **Then** update the matching numbers and `…_notes` in `version.json` on `main`. In this order no instance shows a false "update available" banner; the other order shows one until the property is updated.

The dashboard banners cover the Core library and the Frontend web app (there is no Capture banner). The Core check compares `version.json` with the number in the Core code that each web app actually runs, so a web app left on an older Core shows the "update Core" banner.

**Test pages before they go live.** Push a candidate `Index.html` to a branch (for example `ui-test`) and open the dashboard's usual address with `?branch=ui-test` added (`.../exec?branch=ui-test`). Only that browser tab gets the test page; its title says "BibMan (test page: ui-test)". Everyone else keeps the page on `main`. Branch names may contain only letters, digits, `-`, `_` and `.` (anything else loads `main`); a branch that doesn't exist shows "dashboard unavailable" instead of falling back to `main`. When the test page works, put the same file on `main`, then delete the branch.

**Why test:** Google's page delivery (HtmlService) can reject JavaScript that runs fine in a normal browser. On 29 Oct 2026 a page that passed every local check stopped at "Loading library…" with `Uncaught SyntaxError ... Failed to execute 'write' on 'Document'` in the browser console (F12). If that happens on `main`, restore the previous `Index.html` first, then investigate on a test branch. Narrow it down by putting single parts of the change on separate test branches. On 29 Oct the trigger was in the paper-list rendering code (`renderRows`): an added comment line there, or one longer rewritten line, was enough. The same code without the comment loaded fine. So **always test the exact page** that will go to `main`; a page that loads locally or in a test page with one small difference proves nothing.

**Anything pushed to `main` at the repo root is live for every instance immediately**: `Index.html`, `bookmarklet.js`, `version.json`, `favicon.png` and `synonyms/*.tsv` are fetched from `main` at run time. Test changes to those on a copy before pushing, and don't move or rename them.

## Backups

The database is the only thing that cannot be recreated, and it is large (several GB for a big library), so it is not in git. Two good options:

- **Disk snapshots** (simplest on Google Cloud): Compute Engine → Snapshots → create a snapshot schedule for the VM's boot disk.
- **An online copy** while the service runs: `sudo -u bibman sqlite3 /home/bibman/bibman.db ".backup /path/with/space/bibman-$(date +%F).db"`, then move the copy off the machine. Check free space first (`df -h`); the copy is as big as the database.

To restore onto a fresh server: follow DEPLOY.md but skip `init_db.py`, put the backup at `DB_PATH`, rebuild the index, and start the service.

## Keeping secret files private

Every file holding a key should be readable only by its owner: `ls -l` should show `-rw-------`. On the reference VM this means `/home/bibman/*credentials*.json` and `bibman.service.d/export-credential.conf`. Fix any that aren't with `sudo chmod 600 <file>`; the services run as `bibman` and keep access. To check for strays:
```
sudo find /home/bibman /etc/systemd/system -maxdepth 2 \( -name '*credential*' -o -name '*.json' -o -name 'bibman.service*' \) -type f -perm /o+r -ls
```
This lists any such file that other accounts can still read. An empty result is what you want.

## Adding and removing people

Since 2 November 2026 (Core 9) there is no list of people: the dashboard is open to anyone signed in to Google who has the **dashboard link** and the **access code** (Script Property `BIBMAN_ACCESS_CODE` in the **Frontend** project). Each person enters the code once, in the box BibMan shows or in the link as `?access=CODE`, and BibMan remembers it for them until the code changes. Capitals count; spaces at either end are ignored. If no code is set, nobody can open the dashboard.

**To add someone:** send them the dashboard link and the access code. They install the bookmarklet themselves from **Utilities → Bookmarklet**. If clicking someone's bookmarklet opens a blank Google page (`…googleusercontent.com/userCodeAppPanel…#`), that bookmark holds the dashboard's page address instead of the bookmarklet (it was dragged before the button was ready, which the dashboard prevents since 5 November 2026): delete it and drag a new one. A real bookmarklet's address starts with `javascript:`.

**Admins** (who see the **Admin** menu) are the Google emails listed, separated by commas, in the Frontend's Script Property `ADMIN_EMAILS`.

**Core members** never need the access code: list their Google emails (the address they sign in with), separated by commas, in the Frontend's Script Property `CORE_MEMBERS`. Admins never need it either. Changing the code doesn't affect them; removing someone from the list does, at once (they then need the code like everyone else).

**To shut out everyone you don't give a new code to:** change `BIBMAN_ACCESS_CODE` (Project Settings → Script Properties; no redeploying) and send the new code to those who should keep using BibMan. It takes effect at once: every dashboard action checks the current code, so even an open dashboard stops working until the new code is entered.

**To cut someone off completely:** a new access code is not enough if they have a bookmarklet installed. The bookmarklet carries the shared `GAS_CREDENTIAL`, so it keeps adding papers to the library until that credential changes, and the dashboard hands the same credential to every browser. To revoke all access, including old bookmarklets and any copied credential:

1. Change `BIBMAN_ACCESS_CODE` as above.
2. Replace `GAS_CREDENTIAL` as described under *Rotating secrets* below.
3. Ask everyone who should keep access to re-drag the bookmarklet from **Utilities → Bookmarklet**, since their old one stops working.

gooTeX doesn't use the access code: it reads the bibliography from the server with its own read-only `EXPORT_CREDENTIAL`.

If gooTeX shares the server and still uses `GAS_CREDENTIAL` rather than its own `EXPORT_CREDENTIAL`, update gooTeX in the same sitting, or its bibliographies stop updating.

## Rotating secrets

- **`GAS_CREDENTIAL`** (full access; used by the Frontend and Capture web apps and built into the bookmarklet): generate a new one (`openssl rand -hex 16`), set it in `bibman.service` and in the `GAS_CREDENTIAL` Script Property of the **Frontend** and **Capture** projects (the Core library doesn't store it; Script Properties take effect without redeploying), then `sudo systemctl daemon-reload && sudo systemctl restart bibman`. Users must re-drag the bookmarklet from **Utilities**, since the old one carries the old value. If gooTeX still uses `GAS_CREDENTIAL` rather than its own `EXPORT_CREDENTIAL`, change its `BIBMAN_CREDENTIAL` at the same time, or better, move it to `EXPORT_CREDENTIAL` first (DEPLOY.md, *Using BibMan with gooTeX*).
- **`EXPORT_CREDENTIAL`** (read-only, bibliography export only; used by gooTeX): it lives in its own file, `/etc/systemd/system/bibman.service.d/export-credential.conf`. Change it there and in gooTeX's `BIBMAN_CREDENTIAL` together, then `sudo systemctl daemon-reload` and restart both services.
- **`SESSION_SECRET`**: change it in `bibman.service` and restart.
- **ADS token / Gemini key**: change the Script Properties in the Frontend and Capture projects. Nothing on the server stores them.

## PDFs in Drive

When a paper is added and its PDF can be downloaded, the server saves a copy in `BibMan_PDFs/<library>/<bibkey>.pdf` on the owner's Drive, viewable by anyone with the link, so it opens for every BibMan user without sharing the folder. The server hands the PDF to the **bookmarklet's** web app (it runs as the owner and needs no Google sign-in; it needs the Script Property `PDF_FOLDER_ID`); Apps Script tells the server that address with every request. Until Core 10 the server handed PDFs to the dashboard's web app, which refused them (`401 Unauthorized` in the log), so papers added then have no Drive copy. A PDF with the same name already in that folder is replaced (the old one goes to the Trash). PDFs over 40 MB are not saved (Apps Script can't take much more in one request); the log says so, and they stay readable from their source.

- **Approval first:** the bookmarklet project saves the PDFs as you, so it needs your approval for Drive and the **Drive API** service. Run `authorizeDrive` in its editor once and allow the permissions; it changes nothing and says whether the Drive API service is on. Signs that this is missing: bookmarklet clicks land on a blank Google page with `createOAuthDialog=true` in its address (not approved), or `checkPdfLinks` stops with "Google Drive API has not been used in project … or it is disabled" (service missing: click **+** next to **Services**, choose **Drive API**, **Add**).
- **Viewable by link:** in the bookmarklet project's editor, run `checkPdfLinks` (lists the PDFs in `BibMan_PDFs` and its subfolders that are not viewable by link; changes nothing), then `fixPdfLinks` to switch them. Results are in the Execution log; files owned by someone else are listed rather than changed. Each run stops after about 5 minutes; run `fixPdfLinks` again to carry on.
- **Papers with no Drive copy:** in the same editor, `resavePdfsCheck` shows how many papers have a PDF but no Drive copy (and the progress of a running re-save); `resavePdfsStart` has the server re-save them in the background, one paper every 10 seconds: a PDF of the same name already in Drive is linked, otherwise the PDF is fetched again from its stored link and saved. PDFs over 40 MB are skipped and listed. The report is written next to the database (`bibman_resave_pdfs_<date>.txt`). Running it again only handles what is still missing.

## The PDF proxy Worker

arXiv PDFs, and since Core 10 any other stored PDF link (with the VM fetching it if the Worker can't), reach the dashboard through a Cloudflare Worker (`CF_WORKER_URL` in the frontend's Script Properties). It lives in whichever Cloudflare account created it, which may not be the one that runs your tunnel; the `….<subdomain>.workers.dev` part of its address identifies the account. Its source is [`cloudflare_worker/worker.js`](cloudflare_worker/worker.js). It only answers requests whose path starts with its `PROXY_KEY` secret, which is also the last part of `CF_WORKER_URL`; to change the key, update both. To change it: Workers & Pages → the Worker → **Edit code** → paste → **Deploy**.

## TLS certificate

Certbot renews automatically. Check with `sudo certbot renew --dry-run`.
