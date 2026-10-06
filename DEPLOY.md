# Running your own BibMan

This guide is for a research group that wants its own BibMan server. If you would rather join an existing BibMan instance, you don't need any of this: ask that instance's maintainer to add your group, and read the [README](README.md).

Setting up takes an afternoon for someone comfortable with a Linux command line. Everything can run on free tiers.

## How the pieces fit

```
Browser ──► Frontend web app ─┐
            (Apps Script)     │                          ┌─► nginx (443) ──► gunicorn/Flask 127.0.0.1:8081
                              ├─► BibMan_Core library ───┤                          │
Bookmarklet ─► Capture web app┘   (Apps Script)          │                          ├─► SQLite database (library + embeddings)
            (Apps Script)                                 └─ https://YOUR-SUBDOMAIN.duckdns.org/bibman/…  └─► usearch index (semantic search)
```

- **The server** (`cloud/`) holds the library. It is a Flask app on an always-on Linux VM, reachable only through nginx over HTTPS.
- **Three Google Apps Script projects** (`apps_script/`) sit in front of it. Users only ever see `script.google.com` addresses, which get through most workplace firewalls, and Google handles sign-in.
  - `BibMan_Core_Library`: all the logic, shared by the other two as a library.
  - `BibMan_Frontend_ThinClient_WebApp`: serves the dashboard and checks the access list.
  - `BibMan_Bookmarklet_Capture_ThinClient_WebApp`: receives clicks from the "Add to BibMan" bookmarklet.
- **Files at the root of this repo are served live.** `Index.html` (the dashboard), `bookmarklet.js`, `version.json`, `favicon.png` and `synonyms/*.tsv` are fetched from `github.com/pmarcum/BibMan` at run time, so every instance gets interface updates automatically. If you fork BibMan and want your own interface, change the `raw.githubusercontent.com/pmarcum/BibMan/main/…` URLs in `BibMan_Core_Library/Code.gs`, `BibMan_Frontend_ThinClient_WebApp/Code.gs` and `cloud/bibman_e2micro_server.py` to point at your fork.

### What you need

- An always-on Linux VM. BibMan is developed on a Google Cloud **e2-micro** (1 GB RAM, free tier) running **Debian 12**; anything comparable works. Give it a **static external IP** and open ports 80 and 443.
- A free **[DuckDNS](https://www.duckdns.org)** subdomain pointing at that IP (any domain name works).
- A Google account to own the Apps Script projects, plus a Google Sheet for the access list.
- A **[NASA ADS API token](https://ui.adsabs.harvard.edu/user/settings/token)** (paper metadata) and a **[Gemini API key](https://aistudio.google.com/apikey)** (embeddings for semantic search). These live in Apps Script, not on the server.
- A **Cloudflare Worker** URL for viewing arXiv PDFs in the dashboard (`CF_WORKER_URL`; see [Part 3](#part-3-the-pdf-proxy-worker)).

---

## Part 1: the server

All commands run on the VM.

**1. A small machine needs swap.** On a 1 GB VM, add 2 GB of swap first:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**2. Install system packages and create the `bibman` user:**

```bash
sudo apt update && sudo apt install -y python3-venv git nginx certbot python3-certbot-nginx sqlite3 poppler-utils
sudo adduser --disabled-password --gecos "" bibman
```

**3. Install the code** (as `bibman`):

```bash
sudo -iu bibman
git clone https://github.com/pmarcum/BibMan.git ~/BibMan-repo
mkdir -p ~/bibman && cp ~/BibMan-repo/cloud/*.py ~/BibMan-repo/cloud/schema.sql ~/bibman/
cd ~/bibman && python3 -m venv venv && venv/bin/pip install -r ~/BibMan-repo/cloud/requirements.txt
```

**4. Create an empty database.** Pick a name for your first library:

```bash
DB_PATH=/home/bibman/bibman.db LIBRARY_NAME=MyLibrary venv/bin/python init_db.py
exit   # back to your own account
```

`init_db.py` refuses to run if the database already exists, so it can't overwrite a real library.

**5. Install the service.** Generate two secrets and keep them somewhere safe:

```bash
openssl rand -hex 24   # SESSION_SECRET
openssl rand -hex 16   # GAS_CREDENTIAL — you'll paste this into all three Apps Script projects too
```

```bash
sudo cp /home/bibman/BibMan-repo/cloud/systemd/bibman.service /etc/systemd/system/
sudo nano /etc/systemd/system/bibman.service   # fill in the two REPLACE_ME values and LIBRARY_NAME
sudo systemctl daemon-reload && sudo systemctl enable --now bibman
curl -s http://127.0.0.1:8081/health           # → {"status":"healthy", ...}
```

**6. Put nginx and HTTPS in front of it.** Get the certificate first, while nginx's default site is still answering on port 80:

```bash
sudo certbot certonly --nginx -d yourname.duckdns.org
```

Then install BibMan's site config in place of the default one:

```bash
sudo cp /home/bibman/BibMan-repo/cloud/nginx/proxy-router.conf /etc/nginx/sites-available/proxy-router
sudo sed -i 's/YOUR-SUBDOMAIN/yourname/g' /etc/nginx/sites-available/proxy-router
sudo ln -s /etc/nginx/sites-available/proxy-router /etc/nginx/sites-enabled/ && sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
curl -s https://yourname.duckdns.org/health   # → {"status":"healthy", ...}
```

Certbot renews the certificate automatically.

---

## Part 2: the Apps Script projects

Create these in the Google account that will own your BibMan. In each project, use **Project Settings → Show "appsscript.json" manifest file in editor**, then paste the files from the matching `apps_script/` folder. Script Properties are under **Project Settings → Script Properties**.

### 2a. The access list

Create a Google Sheet with a tab named exactly **`allowed_users`**. Row 1 is a header; from row 2 on:

| A: email | B: name | C | D: admin |
|---|---|---|---|
| alice@university.edu | Alice | | TRUE |
| bob@gmail.com | Bob | | FALSE |

Only rows with both an email and a name count. Column C isn't used by the access check. Note the Sheet's ID (the long string in its URL).

### 2b. `BibMan_Core_Library`

1. New project → paste `Code.gs` and `appsscript.json`.
2. Script Property: `BIBMAN_CORE_LIBRARY_VERSION` = the `bibman_core_library_version` number in [`version.json`](version.json).
3. **Deploy → New deployment → Library.** Copy the project's **Script ID** (Project Settings).

### 2c. `BibMan_Frontend_ThinClient_WebApp` (the dashboard)

1. New project → paste `Code.gs`, `Logo.html` and `appsscript.json`.
2. In `appsscript.json`, replace the `libraryId` with **your** Core Script ID, and set `version` to your Core library's deployment version (`1` for a first deployment).
3. Script Properties:

| Property | Value |
|---|---|
| `GAS_CREDENTIAL` | the value from Part 1, step 5 |
| `DUCKDNS_URL` | `https://yourname.duckdns.org` (no trailing slash) |
| `ADS_TOKEN` | your NASA ADS token |
| `GEMINI_KEY` | your Gemini API key |
| `ACCESS_SHEET_ID` | the access-list Sheet ID |
| `FRONTEND_THINCLIENT_VERSION` | `bibman_frontend_thinclient_webapp_version` from `version.json` |
| `CF_WORKER_URL` | your PDF-proxy Worker URL (Part 3) |
| `BOOKMARKLET_CAPTURE_WEBAPP_URL` | filled in after 2d |
| `PDF_FOLDER_ID` | *optional*: Drive folder where saved PDFs go |
| `EXPORT_FOLDER_ID` | *optional*: Drive folder for `.bib` exports |
| `EMBED_MODEL`, `GENERATE_MODEL` | *optional*: defaults `models/gemini-embedding-001`, `models/gemini-2.0-flash` |
| `CLOUDFLARE_URL` | *optional*: a fallback server URL, tried when DuckDNS doesn't answer |

4. **Deploy → New deployment → Web app**: *Execute as: User accessing the web app*; *Who has access: Anyone with a Google account*. Copy the web app URL. This is your group's dashboard link.
5. In the editor, run `authorizeDrive` once, then `setupCronTrigger` once. The trigger runs the nightly processing (embeddings and synonyms) at 5 am Pacific.

### 2d. `BibMan_Bookmarklet_Capture_ThinClient_WebApp`

1. New project → paste `Code.gs` and `appsscript.json`; replace the `libraryId` with your Core Script ID.
2. Script Properties: `GAS_CREDENTIAL`, `DUCKDNS_URL`, `ADS_TOKEN`, `GEMINI_KEY` (same values as 2c), `BIBMAN_DASHBOARD_URL` (the dashboard URL from 2c), and `BOOKMARKLET_CAPTURE_VERSION` (`bibman_bookmarklet_capture_webapp_version` from `version.json`).
3. **Deploy → New deployment → Web app**: *Execute as: Me*; *Who has access: Anyone*. (Bookmarklet clicks come from arbitrary web pages with no Google sign-in, which is why this one runs as you. Every request except the list of library names is checked against `GAS_CREDENTIAL`.)
4. Put this web app's URL into the frontend's `BOOKMARKLET_CAPTURE_WEBAPP_URL` property.

When you change code later, use **Deploy → Manage deployments → Edit → New version** rather than a new deployment, so the dashboard URL and everyone's bookmarklet keep working.

### 2e. Try it

*Meaning-based search starts working once you have papers: after the nightly job has embedded your first batch, build the search index once (MAINTENANCE.md, "The semantic-search index"). Word and synonym search work from the first paper.*


Open the dashboard URL, go to **Utilities → Bookmarklet**, drag **Add to BibMan** to your bookmarks bar, and use it on an ADS or arXiv page. Then send the dashboard link to the people on your access list.

---

## Part 3: the PDF proxy Worker

The dashboard displays arXiv PDFs through a small Cloudflare Worker: arXiv doesn't send the headers a browser needs to read a PDF from another site, so the Worker fetches the file and adds them. (PDFs from other sites are fetched by your server instead.) The Worker accepts any website, but only answers requests carrying your secret key and only passes on real PDF files.

1. Create a free account at [dash.cloudflare.com](https://dash.cloudflare.com) (or use one you have). Note which account you use; you'll need it if you ever change the Worker.
2. **Workers & Pages → Create → Worker**, give it a name (e.g. `bibman-get-pdf`), and deploy the starter code.
3. Click **Edit code**, replace everything with [`cloudflare_worker/worker.js`](cloudflare_worker/worker.js), and click **Deploy**.
4. Make a key: any long random string (`openssl rand -hex 16` on the server prints one). In the Worker's **Settings → Variables and Secrets**, add a variable of type **Secret** named `PROXY_KEY` with that value.
5. In the frontend's Script Properties, set `CF_WORKER_URL` to the Worker's address **followed by `/` and the key**: `https://bibman-get-pdf.<your-subdomain>.workers.dev/<key>`.

To check it, open `https://bibman-get-pdf.<your-subdomain>.workers.dev/<key>?url=https://arxiv.org/pdf/1706.03762` in a browser: you should see the PDF. Without the key you get `forbidden`.

---

## Security notes

- **`GAS_CREDENTIAL` is the key to your server.** Anyone who has it can read and change the library. It is built into every user's bookmarklet and is sent to the dashboard in each signed-in user's browser, along with the Gemini key, so only put people you trust on the access list. If someone leaves, generate a new value, change it in `bibman.service` and all three projects, restart, and have everyone re-drag the bookmarklet.
- **`/get_bib` has no credential check**, and nothing needs to reach it from outside the VM (gooTeX does not use it). The supplied nginx config blocks it at the public address; keep that block if you edit the config. Don't delete the Python function `get_bib()` itself: the authenticated `/api/export/bib-text` route uses it.
- **Never commit** `bibman.db`, the `.usearch` index, `bibman_config.json`, or a filled-in `bibman.service`. The repo's `.gitignore` covers the common names.

## Using BibMan with gooTeX

[gooTeX](https://github.com/pmarcum/gooTeX) only *reads* bibliographies from BibMan, through three routes:

- its compile server, on the same VM: `POST http://localhost:8081/api/export/bib` with body `{"bibkeys": [...], "library": "<name>"}`, returning `{"bibtex", "found", "missing", "total_requested"}`;
- its Apps Script, through nginx: `GET https://<host>/bibman/api/libraries/<name>/stats` (reads `last_rowid`) and `GET https://<host>/bibman/api/export/bib-text?library=<name>` (the Refs sidebar).

Give gooTeX its own **read-only** key rather than `GAS_CREDENTIAL`:

1. On the VM, put the key in its own small settings file next to the service (your `bibman.service` stays untouched):
   ```
   NEWKEY=$(openssl rand -hex 16); echo "$NEWKEY"        # keep this value; gooTeX needs it
   sudo mkdir -p /etc/systemd/system/bibman.service.d
   printf '[Service]\nEnvironment=EXPORT_CREDENTIAL=%s\n' "$NEWKEY" | sudo tee /etc/systemd/system/bibman.service.d/export-credential.conf >/dev/null
   sudo chmod 600 /etc/systemd/system/bibman.service.d/export-credential.conf
   sudo systemctl daemon-reload && sudo systemctl restart bibman
   ```
   BibMan accepts this key on the three routes above and refuses it everywhere else. Check it: `curl -s -o /dev/null -w "%{http_code}\n" -H "X-BibMan-Credential: $NEWKEY" "https://<host>/bibman/api/export/bib-text?library=<name>"` prints `200`, and the same request to `/bibman/api/papers` prints `401`. To remove the key, delete that file, then `daemon-reload` and restart.
2. Put the same value in gooTeX's `BIBMAN_CREDENTIAL` (its systemd drop-in and its template `Config.js`). gooTeX's name means "the credential for reaching BibMan"; its value is BibMan's `EXPORT_CREDENTIAL`.

That way gooTeX, and anyone who can open a gooTeX document's script, holds a key that can read bibliographies but not change or delete anything. If gooTeX shares the server, keep BibMan on `127.0.0.1:8081`, keep the `/bibman/` nginx route, and don't change those three routes' request or response shapes. Keep the `/gootex/` block in the nginx config only if gooTeX runs on the same machine.
