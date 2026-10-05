/**
 * BibMan Thin Client Shell
 * ========================
 * This is the ONLY code file each research group needs to deploy.
 * All business logic lives in the BibMan_Core library (managed centrally).
 * The dashboard UI (Index.html) is fetched live from GitHub at serve time,
 * so ALL groups always see the latest UI with zero manual intervention.
 *
 * Files in this GAS project:
 *   Code.gs      ← this file (the ONLY file needed)
 *
 * Setup:
 *   1. Create a new Google Apps Script project.
 *   2. Add BibMan_Core as a library (Extensions → Libraries → paste Script ID).
 *      Use identifier: BibManCore
 *   3. Add your Script Properties (Project Settings → Script Properties):
 *        GAS_CREDENTIAL                 = shared secret from your BibMan admin
 *        DUCKDNS_URL                    = https://YOUR-SUBDOMAIN.duckdns.org
 *        CLOUDFLARE_URL                 = https://xxxx.trycloudflare.com  (auto-updated by VM)
 *        ADS_TOKEN                      = your NASA ADS API token
 *        GEMINI_KEY                     = your Google Gemini API key
 *        ACCESS_SHEET_ID                = Spreadsheet ID containing allowed_users tab
 *        PDF_FOLDER_ID                  = Drive folder ID for BibMan_PDFs parent
 *        BOOKMARKLET_CAPTURE_WEBAPP_URL = URL of BibMan_Bookmarklet_Capture_webapp
 *        CF_WORKER_URL                  = Cloudflare Worker URL (optional)
 *        EXPORT_FOLDER_ID               = Drive folder ID for .bib exports (optional)
 *        EMBED_MODEL                    = models/gemini-embedding-001 (optional)
 *        GENERATE_MODEL                 = models/gemini-2.0-flash     (optional)
 *        BIBMAN_DASHBOARD_URL           = this webapp's URL (optional)
 *   4. Deploy as Web App:
 *        Execute as: User accessing the web app
 *        Who has access: Anyone with Google account
 *   5. Run setupCronTrigger() once from the script editor.
 *   6. Run authorizeDrive() once from the script editor.
 *
 * Keeping up to date:
 *   - BibMan_Core updates: Extensions → Libraries → change version → save.
 *     The dashboard will show a banner when a new Core version is available.
 *   - UI updates (Index.html): fetched live from GitHub — nothing to do!
 *     UI changes are instant for all groups automatically.
 *   - Code.gs (this file) updates: replace Code.gs with the new version from
 *     https://github.com/pmarcum/BibMan and redeploy (new version).
 *     The dashboard will show a banner when a Code.gs update is available.
 *
 * IMPORTANT: After deploying, do NOT create a new deployment for updates.
 * Always edit the existing deployment and select "New version" so the URL
 * remains stable for all team members and the bookmarklet.
 */

// ── Thin client version ────────────────────────────────────────────────────────
// Tracks changes to THIS file (Code.gs) only.
// UI changes (Index.html) are delivered automatically via GitHub fetch —
// they do NOT require a version bump here.
// When you replace Code.gs with a new version from GitHub, update this number
// to match bibman_frontend_thinclient_webapp_version in version.json.
// THE VERSION NUMBER IS IN SCRIPT PROPERTIES! CHANGE IT IN THERE!

// ── Config builder ─────────────────────────────────────────────────────────────
function _cfg() {
  const p = PropertiesService.getScriptProperties();
  return {
    credential:                p.getProperty('GAS_CREDENTIAL')             || '',
    duckdnsUrl:                p.getProperty('DUCKDNS_URL')                || '',
    cloudflareUrl:             p.getProperty('CLOUDFLARE_URL')             || '',
    adsToken:                  p.getProperty('ADS_TOKEN')                  || '',
    geminiKey:                 p.getProperty('GEMINI_KEY')                 || '',
    embedModel:                p.getProperty('EMBED_MODEL')                || 'models/gemini-embedding-001',
    generateModel:             p.getProperty('GENERATE_MODEL')             || 'models/gemini-2.0-flash',
    pdfFolderId:               p.getProperty('PDF_FOLDER_ID')              || '',
    exportFolderId:            p.getProperty('EXPORT_FOLDER_ID')           || '',
    cfWorkerUrl:               p.getProperty('CF_WORKER_URL')              || '',
    captureUrl:                p.getProperty('BOOKMARKLET_CAPTURE_WEBAPP_URL')         || '',
    accessSheetId:             p.getProperty('ACCESS_SHEET_ID')            || '',
    dashUrl:                   p.getProperty('BIBMAN_DASHBOARD_URL')       || ScriptApp.getService().getUrl(),
    // Version info — compared against version.json on GitHub by BibMan_Core
    frontendThinClientVersion: parseInt(p.getProperty('FRONTEND_THINCLIENT_VERSION'), 10) || 1,
    linkedCoreVersion:         BibManCore.getCoreVersion(),
  };
}

// ── Web app entry points ───────────────────────────────────────────────────────
// doGet MUST live here — GAS libraries cannot serve HtmlService output.
// Access control logic is delegated to BibMan_Core.getAllowedUsers().
// Index.html is fetched live from GitHub so all groups always have the
// latest UI with zero manual intervention.
function doGet(e) {
  if (e && e.parameter && e.parameter.auth === '1') {
    return HtmlService.createHtmlOutput(BibManCore.getAuthSuccessHtml())
      .setTitle('BibMan — Authorized');
  }
  const config = _cfg();
  const email   = Session.getActiveUser().getEmail();
  const users   = BibManCore.getAllowedUsers(config);
  const allowed = users.map(u => u.email);
  if (!allowed.includes(email.toLowerCase())) {
    return HtmlService.createHtmlOutput(BibManCore.getAccessDeniedHtml(email))
      .setTitle('BibMan — Access Denied');
  }
  let htmlContent = BibManCore.fetchDashboardHtml();
  try {
    const logoHtml = HtmlService.createHtmlOutputFromFile('Logo').getContent();
    htmlContent = htmlContent.replace('<!--LOGO_PLACEHOLDER-->', logoHtml);
  } catch(err) {}
  return HtmlService
    .createHtmlOutput(htmlContent)
    .setTitle('BibMan')
    .setFaviconUrl('https://raw.githubusercontent.com/pmarcum/BibMan/main/favicon.png')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  const config = _cfg();
  const result = BibManCore.doPost(config, e);
  // BibManCore.doPost returns a sentinel for update_tunnel_url because
  // Script Properties can only be written from the bound script, not a library.
  if (result && result._action === 'write_cloudflare_url') {
    PropertiesService.getScriptProperties()
      .setProperty('CLOUDFLARE_URL', result.url || '');
    return ContentService.createTextOutput(
      JSON.stringify({ ok: true })
    ).setMimeType(ContentService.MimeType.JSON);
  }
  return result;
}

// ── Single dispatcher for all browser → GAS calls ─────────────────────────────
// Index.html calls: google.script.run.gas('functionName', arg1, arg2, ...)
function gas(fn, ...args) { return BibManCore.dispatch(_cfg(), fn, ...args); }

// ── Cron (time-based triggers can only fire bound-script functions) ─────────────
function runNightlyCron() { return BibManCore.runNightlyCron(_cfg()); }

function setupCronTrigger() { return BibManCore.setupCronTrigger(); }

// ── One-time setup helpers (run manually from script editor) ───────────────────
/**
 * authorizeDrive: Run once after deployment to pre-authorize Drive scope.
 */
function authorizeDrive() {
  const cfg = _cfg();
  if (!cfg.pdfFolderId) {
    const f = DriveApp.getRootFolder().createFolder('_bibman_auth_test_delete_me');
    f.setTrashed(true);
    Logger.log('authorizeDrive: authorized via Drive root (PDF_FOLDER_ID not set)');
  } else {
    const folder = DriveApp.getFolderById(cfg.pdfFolderId);
    const f = folder.createFolder('_bibman_auth_test_delete_me');
    f.setTrashed(true);
    Logger.log('authorizeDrive: authorized via PDF_FOLDER_ID folder');
  }
}

function forceAuth() {
  Logger.log(Session.getActiveUser().getEmail());
  Logger.log(DriveApp.getRootFolder().getName());
}
