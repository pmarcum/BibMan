# Maintaining a BibMan server

For whoever hosts a BibMan instance. Setup is in [DEPLOY.md](DEPLOY.md). This page covers keeping it running, updating it, and recovering it.

## Where things live on the VM

| Path | What it is |
|---|---|
| `/home/bibman/bibman/` | Server code (`bibman_e2micro_server.py`, `bibman_cron.py`, `bibman_rebuild_usearch.py`) and its `venv/` |
| `/home/bibman/bibman.db` | The SQLite database: every library, paper, passage, annotation, tag, and the 3072-dim Gemini embeddings (`vec_passages`, `vec_annotations`). **This is the data. It is not in git.** |
| `/home/bibman/bibman_768_i8.usearch` | Semantic-search index, loaded into memory when the service starts. Can always be rebuilt from the database. |
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
sudo systemctl restart bibman                # restart (takes a few seconds; reloads the index)
curl -s https://YOUR-SUBDOMAIN.duckdns.org/health
```

## Scheduled jobs

| Job | Runs from | When | What it does |
|---|---|---|---|
| Nightly processing (`runNightlyCron`) | Apps Script time trigger in the **Frontend** project (created once by `setupCronTrigger`) | Daily, about 5 am Pacific | Calls `POST /api/cron/run` with the Gemini key; the server then embeds new passages and generates synonym pairs in the background, in small batches |
| Search-index rebuild | **Not scheduled**: run by hand (see "The semantic-search index") | After adding a batch of papers, or monthly | Rebuilds the usearch file from the stored embeddings |

**Why the nightly job runs from Apps Script and not from the VM's crontab:** the VM never stores the Gemini key. Each user's key lives only in Script Properties and is sent with each request, so a job on the VM would have no key to use. The Apps Script trigger supplies it each night. This also means a compromised VM exposes no Gemini key at rest. (The old crontab lines, and those in `bibman_cron.py`'s docstring, are disabled and superseded.)

**Why the index rebuild isn't scheduled:** on an e2-micro it is slow and heavy (about 4 hours for ~390,000 passages, because the e2-micro is held to about a quarter of a CPU for sustained work; a few hundred MB of memory), it should run when nobody is using BibMan or gooTeX, and the new index only takes effect after a restart. A person should watch it and check the result.

BibMan needs no crontab entries on the VM. If gooTeX shares the VM, its own monthly cache cleanup is in the `bibman` user's crontab; leave that alone.

To check the nightly trigger: open the Frontend project → **Triggers** (clock icon) → `runNightlyCron`. Its executions log (**Executions**, the list icon) shows whether each night's run succeeded.

## The semantic-search index

**How it works**
- **Embeddings:** Gemini returns 3072-dimensional embeddings, and they are stored at full size in the database.
- **The index:** for speed and to fit in 1 GB of RAM, meaning-based search uses a separate **usearch** index. It holds the first 768 dimensions of each embedding (Gemini embeddings are designed to be truncated this way), compressed to int8. On a large library it is a few hundred MB. Never build it as float16 or at more dimensions on an e2-micro: it will not fit in memory.
- **Keys:** index keys are each passage's `search_id`, a 60-bit number taken from the first 15 hex digits of the passage's UUID: `int(uuid.replace('-', '')[:15], 16)` (the rule the April 2026 migration used). **Why 15 digits, not 16:** SQLite stores integers as *signed* 64-bit numbers (largest 2^63 − 1). Sixteen hex digits make a 64-bit number, which is too big for about half of all UUIDs, and the April migration failed on them; fifteen digits (60 bits) always fit. (usearch itself accepts any unsigned 64-bit key, so it is not the limit.) **Uniqueness:** in a random (version 4) UUID the 13th hex digit is always `4`, so those 15 digits carry 56 random bits, about 7×10^16 possible IDs. The chance of any two passages sharing an ID is about n²/(2×2^56): roughly 1 in a million at 390,000 passages, and still under 1 in 1,000 at 10 million passages (about 25 times this library). A shared ID can't detach notes or tags, which are linked by UUID; at worst one meaning-search hit would show the wrong passage. `bibman_backfill_search_ids.py` refuses to write any ID that would collide. **Never change this rule:** every existing ID and the index keys depend on it. Search results are mapped back to passages through that column. The server sets it for every new passage (since 6 Oct 2026). Before that, passages added after the April 2026 migration got none.
- **Compression method:** `bibman_768_i8.usearch.method`, written by the rebuild script, records how vectors were compressed. The server reads it at startup and compresses search queries the same way. With no file, it assumes the original April 2026 method (A).

**The index is a snapshot.** It does not update itself as papers are added. New papers are found by word and synonym search straight away, but meaning-based search only finds them after a rebuild. Rebuild after adding a batch of papers, or monthly.

**Scripts** (in `cloud/`, installed in `/home/bibman/bibman/`; all run as `bibman` with BibMan's Python):

| Script | What it does | Changes anything? |
|---|---|---|
| `bibman_search_check.py` | Counts passages missing a search ID, verifies the ID formula against existing IDs, identifies how the live index was built, measures search accuracy on a sample, and reports disk and memory. | No (read-only) |
| `bibman_backfill_search_ids.py` | Fills in missing search IDs. Dry run by default; `--apply` writes. It refuses to write unless the formula reproduces every existing ID and no new ID collides. | Only with `--apply`, and only rows that have no ID |
| `bibman_rebuild_usearch.py` | Rebuilds the index from stored embeddings (no Gemini calls). It writes to a temporary file, checks it, keeps the current index as `bibman_768_i8.usearch.prev`, then installs the new one. It does not restart BibMan. | The index files only; the database is opened read-only |

**Rebuilding.** Do this when nobody is using BibMan **or gooTeX**. The build needs about 420 MB of memory for a 390,000-passage library, and `nice` lowers its CPU priority but not its memory use.

1. **Back up first:** take a snapshot of the VM's disk (Compute Engine → Disks → the VM's disk → *Create snapshot*). It costs cents and covers everything, including the database.
2. **Run the scripts:**
```
cd /home/bibman/bibman
sudo -u bibman venv/bin/python bibman_backfill_search_ids.py            # dry run: how many IDs are missing
sudo -u bibman venv/bin/python bibman_backfill_search_ids.py --apply    # only if the dry run said OK
sudo -u bibman venv/bin/python bibman_rebuild_usearch.py --dry-run      # checks paths and the .prev backup
# about 4 hours for ~390,000 passages on an e2-micro; runs in the background, so a dropped SSH session doesn't stop it
sudo -u bibman nohup nice -n 19 venv/bin/python bibman_rebuild_usearch.py > ~/rebuild.log 2>&1 &
tail -f ~/rebuild.log                          # watch progress (Ctrl+C stops watching, not the rebuild); wait for "installed"
sudo systemctl restart bibman
sudo journalctl -u bibman -n 8 --no-pager     # expect "USearch index loaded: N vectors" and "compression method: C"
```
3. **About the old index:** the rebuild keeps it as `bibman_768_i8.usearch.prev` and **refuses to overwrite** an existing `.prev`. For later routine rebuilds, once you're happy with the current index, add `--replace-prev` (or delete the old `.prev` yourself).
4. **About the fill-in:** `bibman_backfill_search_ids.py` also narrows the database trigger `passages_au` so it fires only when a passage's *text* changes. Before, setting an ID would also rewrite that passage's keyword-index entry. New installations get the narrowed trigger from `schema.sql`.

**To go back to the previous index:**
```
sudo -u bibman /home/bibman/bibman/venv/bin/python /home/bibman/bibman/bibman_rebuild_usearch.py --rollback
sudo systemctl restart bibman
```
This swaps the index and its method file with the `.prev` pair. Running it again swaps them back.

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

Every deployed instance compares its own version numbers with [`version.json`](version.json) on `main` and shows an "update available" banner in the dashboard when it is behind. Each project's current number is a **Script Property**, not code:

| Component | Script Property | `version.json` key |
|---|---|---|
| Core library | `BIBMAN_CORE_LIBRARY_VERSION` (in the Core project) | `bibman_core_library_version` |
| Frontend web app | `FRONTEND_THINCLIENT_VERSION` | `bibman_frontend_thinclient_webapp_version` |
| Capture web app | `BOOKMARKLET_CAPTURE_VERSION` | `bibman_bookmarklet_capture_webapp_version` |

Current versions (October 2026): Core library **3** (adds the per-call access check), used by the dashboard web app. The bookmarklet-capture web app is still pinned to Core 1, which is fine: it doesn't use the changed code. When you publish, set `bibman_core_library_version` in `version.json` **and** the Core project's `BIBMAN_CORE_LIBRARY_VERSION` Script Property to `3` together. Otherwise your own dashboard shows an "update available" banner.

To release a change to one of them: update its files in `apps_script/`, deploy a new version in the Apps Script editor (for the Core library, also move each web app's library version up under **Libraries**), bump its Script Property, then bump the matching number and `…_notes` text in `version.json`.

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

**To add someone:** add a row to the `allowed_users` tab of the access-list Sheet (column A their Google email, column B their name, column D `TRUE` if they should be an admin), then send them the dashboard link. They install the bookmarklet themselves from **Utilities → Bookmarklet**.

**To remove someone from the dashboard:** delete their row. They lose the dashboard within about 5 minutes; that's how long a successful access check is remembered.

**To cut someone off completely:** removing the row is not enough if they have a bookmarklet installed. The bookmarklet carries the shared `GAS_CREDENTIAL`, so it keeps adding papers to the library until that credential changes. To revoke all access, including old bookmarklets and any copied credential:

1. Delete their row from `allowed_users`.
2. Replace `GAS_CREDENTIAL` as described under *Rotating secrets* below.
3. Ask everyone who should keep access to re-drag the bookmarklet from **Utilities → Bookmarklet**, since their old one stops working.

If gooTeX shares the server and still uses `GAS_CREDENTIAL` rather than its own `EXPORT_CREDENTIAL`, update gooTeX in the same sitting, or its bibliographies stop updating.

## Rotating secrets

- **`GAS_CREDENTIAL`** (full access; used by the Frontend and Capture web apps and built into the bookmarklet): generate a new one (`openssl rand -hex 16`), set it in `bibman.service` and in the `GAS_CREDENTIAL` Script Property of the **Frontend** and **Capture** projects (the Core library doesn't store it; Script Properties take effect without redeploying), then `sudo systemctl daemon-reload && sudo systemctl restart bibman`. Users must re-drag the bookmarklet from **Utilities**, since the old one carries the old value. If gooTeX still uses `GAS_CREDENTIAL` rather than its own `EXPORT_CREDENTIAL`, change its `BIBMAN_CREDENTIAL` at the same time, or better, move it to `EXPORT_CREDENTIAL` first (DEPLOY.md, *Using BibMan with gooTeX*).
- **`EXPORT_CREDENTIAL`** (read-only, bibliography export only; used by gooTeX): it lives in its own file, `/etc/systemd/system/bibman.service.d/export-credential.conf`. Change it there and in gooTeX's `BIBMAN_CREDENTIAL` together, then `sudo systemctl daemon-reload` and restart both services.
- **`SESSION_SECRET`**: change it in `bibman.service` and restart.
- **ADS token / Gemini key**: change the Script Properties in the Frontend and Capture projects. Nothing on the server stores them.

## The PDF proxy Worker

arXiv PDFs reach the dashboard through a Cloudflare Worker (`CF_WORKER_URL` in the frontend's Script Properties). It lives in whichever Cloudflare account created it, which may not be the one that runs your tunnel; the `….<subdomain>.workers.dev` part of its address identifies the account. Its source is [`cloudflare_worker/worker.js`](cloudflare_worker/worker.js). It only answers requests whose path starts with its `PROXY_KEY` secret, which is also the last part of `CF_WORKER_URL`; to change the key, update both. To change it: Workers & Pages → the Worker → **Edit code** → paste → **Deploy**.

## TLS certificate

Certbot renews automatically. Check with `sudo certbot renew --dry-run`.
