/**
 * BibMan Bookmarklet Capture — Thin Client Shell
 * ============================================
 * Serves the bookmarklet's window (since Capture 18, with Core 19: the bookmarklet opens this web app's address with
 * ?capture=1, and the window's requests come back through captureCall), handles POST requests from older bookmarklets
 * and the server, and (since Capture 12) shows guests the page from which they drag a guest bookmarklet (this web app's
 * address + ?guest=KEY; the dashboard gives out that link). Delegates all logic to BibMan_Core.
 *
 * Deploy as Web App:
 *   Execute as: Me (the deployer) ← correct, bookmarklet POSTs have no
 *               visiting Google user identity to capture
 *   Who has access: Anyone
 *
 * Script Properties needed:
 *   GAS_CREDENTIAL       — shared secret with Flask and bookmarklet
 *   DUCKDNS_URL          — primary Flask server URL
 *   CLOUDFLARE_URL       — fallback Flask server URL (auto-updated by VM)
 *   ADS_TOKEN            — NASA ADS API token
 *   GEMINI_KEY           — Google Gemini API key
 *   EMBED_MODEL          — optional, default: models/gemini-embedding-001
 *   GENERATE_MODEL       — optional, default: models/gemini-2.0-flash
 *   BIBMAN_DASHBOARD_URL — the BibMan_ThinClient_WebApp URL (for bookmarklet)
 *   PDF_FOLDER_ID        — Drive folder ID of BibMan_PDFs (same value as in the dashboard project): new papers'
 *                          PDFs are saved there by this web app, as you (Core 10)
 *
 * First run, and after any update that needs new access: in the editor, choose authorizeDrive and click Run, and
 * allow the permissions. Until you approve, every bookmarklet click lands on a blank Google page whose address
 * contains createOAuthDialog=true. The project also needs the Drive API service (Services → + → Drive API, v3,
 * identifier Drive; included in appsscript.json for new installs); authorizeDrive says if it is missing.
 *
 * Keeping up to date:
 *   The dashboard will show a banner when a capture webapp update is available.
 *   Users who only use the bookmarklet will see a notice strip in the bookmarklet's window.
 *   To update: replace this Code.gs with the new version from GitHub,
 *   bump BOOKMARKLET_CAPTURE_VERSION to match version.json, and redeploy (new version).
 *
 * This file should rarely need to change. New BibMan features are
 * deployed by updating BibMan_Core centrally.
 */
// ── Capture thin client version ───────────────────────────────────────────────────
// Checked against bibman_bookmarklet_capture_webapp_version in version.json on GitHub.
// When you install an updated capture thin client, bump this to match.
// The SCRIPT PROPERTY BOOKMARKLET_CAPTURE_VERSION is WHERE you set the VERSION VALUE
//    (click on Gears/settings -> scroll down to bottom section, Script Properties)

// ── Config builder ─────────────────────────────────────────────────────────────
// Its name ENDS with _ so that Google keeps it private: a page this web app serves can call any of the project's
// functions by name (google.script.run) unless the name ends with _. Until 16 Nov 2026 it was called _cfg, which
// anyone who could open the web app could call, and it returns every Script Property (credential, keys).
function cfg_() {
  const p = PropertiesService.getScriptProperties();
  return {
    credential:                p.getProperty('GAS_CREDENTIAL')             || '',
    duckdnsUrl:                p.getProperty('DUCKDNS_URL')                || '',
    cloudflareUrl:             p.getProperty('CLOUDFLARE_URL')             || '',
    adsToken:                  p.getProperty('ADS_TOKEN')                  || '',
    geminiKey:                 p.getProperty('GEMINI_KEY')                 || '',
    embedModel:                p.getProperty('EMBED_MODEL')                || 'models/gemini-embedding-001',
    generateModel:             p.getProperty('GENERATE_MODEL')             || 'models/gemini-2.0-flash',
    captureUrl:                ScriptApp.getService().getUrl(),
    pdfFolderId:               p.getProperty('PDF_FOLDER_ID')              || '',
    dashUrl:                   p.getProperty('BIBMAN_DASHBOARD_URL')       || '',
    // Version info — compared against version.json on GitHub by BibMan_Core
    bookmarkletCaptureVersion: parseInt(p.getProperty('BOOKMARKLET_CAPTURE_VERSION'), 10) || 1,
    linkedCoreVersion:         BibManCore.getCoreVersion(),
    frontendThinClientVersion: 1,  // capture webapp doesn't know thin client version; safe default
  };
}

// ── Web app entry points ───────────────────────────────────────────────────────
function doPost(e) { return BibManCore.captureDoPost(cfg_(), e); }
// ?capture=1: the bookmarklet's window (Capture 18, needs Core 19 or later); otherwise a guest's install page (Capture 12)
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (p.capture) return HtmlService.createHtmlOutput(BibManCore.captureWindowPage(cfg_(), p)).setTitle('Add to BibMan')
                          .addMetaTag('viewport', 'width=device-width, initial-scale=1');
  return HtmlService.createHtmlOutput(BibManCore.captureGuestPage(cfg_(), p)).setTitle('BibMan guest bookmarklet');
}
// The window's requests (Capture 18): the same actions and checks as doPost
function captureCall(data) { return BibManCore.captureAction(cfg_(), data); }

// ── Functions for the editor only ───────────────────────────────────────────────
// Pages this web app serves (a guest's install page, the bookmarklet's window) could call the functions below by name,
// and they run as the owner, so each one first checks that the owner started it (Capture 18). Run from the editor, as
// always: the active user there is the owner. Anyone else, signed in or not, is refused.
function ownerOnly_() {
  const who = (Session.getActiveUser().getEmail() || '').toLowerCase(), me = (Session.getEffectiveUser().getEmail() || '').toLowerCase();
  if (!who || who !== me) throw new Error('Only the owner of this project can run this, from the Apps Script editor.');
}

// ── One-time PDF check (run from the editor: select the function, then Run; results in the Execution log) ──
// checkPdfLinks lists the PDFs in BibMan_PDFs that are not "viewable by anyone with the link" and changes nothing;
// fixPdfLinks switches them. Both stop after about 5 minutes; run fixPdfLinks again to carry on.
function checkPdfLinks() { ownerOnly_(); return BibManCore.checkPdfLinks(cfg_(), false); }
function fixPdfLinks()   { ownerOnly_(); return BibManCore.checkPdfLinks(cfg_(), true); }
// resavePdfsCheck shows the papers whose PDF never reached Drive (and the progress of a running re-save), changing
// nothing; resavePdfsStart has the server re-save them in the background (one paper every 10 s).
function resavePdfsCheck() { ownerOnly_(); return BibManCore.resaveMissingPdfs(cfg_(), false); }
function resavePdfsStart() { ownerOnly_(); return BibManCore.resaveMissingPdfs(cfg_(), true); }

// ── Approve Drive access (run once from the editor: select authorizeDrive, then Run; changes nothing) ─────────────
// This web app saves new papers' PDFs into Drive as you, so Google needs your approval first. authorizeDrive opens the
// PDF folder (which makes Google ask), checks that the Drive API service is on (checkPdfLinks needs it), and says so.
function authorizeDrive() {
  ownerOnly_();
  const id = PropertiesService.getScriptProperties().getProperty('PDF_FOLDER_ID');
  if (!id) throw new Error('PDF_FOLDER_ID is not set: add it in Project Settings → Script Properties (same value as in the dashboard project)');
  const folder = DriveApp.getFolderById(id);
  const r = UrlFetchApp.fetch('https://www.googleapis.com/drive/v3/files?pageSize=1&fields=files(id)&q=' +
                              encodeURIComponent("'" + id + "' in parents and trashed=false"),
                              { headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }, muteHttpExceptions: true });
  const code = r.getResponseCode();
  const api = code === 200 ? 'the Drive API is on'
            : (code === 403 && /has not been used|is disabled|SERVICE_DISABLED/.test(r.getContentText()))
              ? 'the Drive API is OFF: click + next to Services, choose Drive API (v3, identifier Drive), click Add, then run authorizeDrive again'
              : 'the Drive API check failed (HTTP ' + code + '): ' + r.getContentText().slice(0, 200);
  const text = 'Drive access approved; PDF folder "' + folder.getName() + '" found; ' + api + '.';
  Logger.log(text);
  return text;
}
