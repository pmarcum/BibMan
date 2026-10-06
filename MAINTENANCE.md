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

## Nightly processing

Some work is too slow to do while a user waits for a paper to be added: generating embeddings for new passages and generating synonym pairs. The dashboard project's time trigger (created by `setupCronTrigger`) calls `POST /api/cron/run` once a day at 5 am Pacific, passing the Gemini key, and the server does the work in the background in small batches. There is no server-side crontab for this; the old cron lines in `bibman_cron.py`'s docstring are superseded.

To check the trigger: open the Frontend project → **Triggers** (clock icon) → `runNightlyCron`.

## The semantic-search index

- Gemini returns 3072-dimensional embeddings; they are stored at full size in the database.
- For speed and to fit in 1 GB of RAM, search uses a separate **usearch** index holding the first 768 dimensions of each embedding (Gemini embeddings are designed to be truncated this way), quantized to int8. On a large library it is a few hundred MB. Never build it as float16 or at more dimensions on an e2-micro: it will not fit in memory.
- Index keys are each passage's `search_id`, a 63-bit number derived from the first 16 hex digits of the passage's UUID: `int(uuid.replace('-', '')[:16], 16) & 0x7FFFFFFFFFFFFFFF`. Search results are mapped back to passages through that column.
- **The index is a snapshot.** It does not update itself as papers are added; new papers are still found by word and synonym search, but they only appear in meaning-based results after the index is rebuilt.

Rebuild it with `bibman_rebuild_usearch.py` (it reads embeddings already in the database, so it makes no Gemini calls), then restart the service to load the new index. Before relying on it, check the two known issues below.

### Known issues with the index rebuild

1. **New passages don't get a `search_id`.** The add-paper code inserts passages without filling `passages.search_id`, and the rebuild only indexes passages that have one. Fill the missing ones before rebuilding, e.g. in Python against the database: `UPDATE passages SET search_id = ? WHERE id = ?` for every row where `search_id IS NULL`, using the formula above.
2. **The rebuild writes the index next to the script, not next to the database.** `bibman_rebuild_usearch.py` saves to `/home/bibman/bibman/bibman_768_i8.usearch`, but the server loads `/home/bibman/bibman_768_i8.usearch`. Move the new file (and its `.timestamp`) up one folder before restarting. The script also expects the sqlite-vec library as `vec0.so` beside it: copy it from the venv (`venv/bin/python -c "import sqlite_vec; print(sqlite_vec.loadable_path())"` prints its location).

Run rebuilds when nobody is using BibMan: on a 1 GB machine the rebuild competes with the running service for memory.

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

To release a change to one of them: update its files in `apps_script/`, deploy a new version in the Apps Script editor (for the Core library, also move each web app's library version up under **Libraries**), bump its Script Property, then bump the matching number and `…_notes` text in `version.json`.

**Anything pushed to `main` at the repo root is live for every instance immediately**: `Index.html`, `bookmarklet.js`, `version.json`, `favicon.png` and `synonyms/*.tsv` are fetched from `main` at run time. Test changes to those on a copy before pushing, and don't move or rename them.

## Backups

The database is the only thing that cannot be recreated, and it is large (several GB for a big library), so it is not in git. Two good options:

- **Disk snapshots** (simplest on Google Cloud): Compute Engine → Snapshots → create a snapshot schedule for the VM's boot disk.
- **An online copy** while the service runs: `sudo -u bibman sqlite3 /home/bibman/bibman.db ".backup /path/with/space/bibman-$(date +%F).db"`, then move the copy off the machine. Check free space first (`df -h`); the copy is as big as the database.

To restore onto a fresh server: follow DEPLOY.md but skip `init_db.py`, put the backup at `DB_PATH`, rebuild the index, and start the service.

## Rotating secrets

- **`GAS_CREDENTIAL`**: generate a new one (`openssl rand -hex 16`), set it in `bibman.service` and in the Script Properties of all three Apps Script projects, then `sudo systemctl daemon-reload && sudo systemctl restart bibman`. Users must re-drag the bookmarklet from **Utilities**, since the old one carries the old value.
- **`SESSION_SECRET`**: change it in `bibman.service` and restart.
- **ADS token / Gemini key**: change the Script Properties in the Frontend and Capture projects. Nothing on the server stores them.

## The PDF proxy Worker

arXiv PDFs reach the dashboard through a Cloudflare Worker (`CF_WORKER_URL` in the frontend's Script Properties). It lives in whichever Cloudflare account created it, which may not be the one that runs your tunnel; the `….<subdomain>.workers.dev` part of its address identifies the account. Its source is [`cloudflare_worker/worker.js`](cloudflare_worker/worker.js). It only answers requests whose path starts with its `PROXY_KEY` secret, which is also the last part of `CF_WORKER_URL`; to change the key, update both. To change it: Workers & Pages → the Worker → **Edit code** → paste → **Deploy**.

## TLS certificate

Certbot renews automatically. Check with `sudo certbot renew --dry-run`.
