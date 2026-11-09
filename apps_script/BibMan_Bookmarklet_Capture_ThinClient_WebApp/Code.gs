/**
 * BibMan Bookmarklet Capture — Thin Client Shell
 * ============================================
 * Handles all bookmarklet POST requests, and (since Capture 12) shows guests the page from which they drag a guest
 * bookmarklet (this web app's address + ?guest=KEY; the dashboard gives out that link). Delegates all logic to BibMan_Core.
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
 *   Users who only use the bookmarklet will see a notice strip in the overlay.
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
function doPost(e) { return BibManCore.captureDoPost(_cfg(), e); }
// A guest's install page (Capture 12, needs Core 12 or later)
function doGet(e) {
  return HtmlService.createHtmlOutput(BibManCore.captureGuestPage(_cfg(), (e && e.parameter) || {}))
    .setTitle('BibMan guest bookmarklet');
}

// ── One-time PDF check (run from the editor: select the function, then Run; results in the Execution log) ──
// checkPdfLinks lists the PDFs in BibMan_PDFs that are not "viewable by anyone with the link" and changes nothing;
// fixPdfLinks switches them. Both stop after about 5 minutes; run fixPdfLinks again to carry on.
function checkPdfLinks() { return BibManCore.checkPdfLinks(_cfg(), false); }
function fixPdfLinks()   { return BibManCore.checkPdfLinks(_cfg(), true); }
// resavePdfsCheck shows the papers whose PDF never reached Drive (and the progress of a running re-save), changing
// nothing; resavePdfsStart has the server re-save them in the background (one paper every 10 s).
function resavePdfsCheck() { return BibManCore.resaveMissingPdfs(_cfg(), false); }
function resavePdfsStart() { return BibManCore.resaveMissingPdfs(_cfg(), true); }

// ── Approve Drive access (run once from the editor: select authorizeDrive, then Run; changes nothing) ─────────────
// This web app saves new papers' PDFs into Drive as you, so Google needs your approval first. authorizeDrive opens the
// PDF folder (which makes Google ask), checks that the Drive API service is on (checkPdfLinks needs it), and says so.
function authorizeDrive() {
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
