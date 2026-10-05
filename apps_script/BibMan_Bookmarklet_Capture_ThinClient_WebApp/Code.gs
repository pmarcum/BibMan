/**
 * BibMan Bookmarklet Capture — Thin Client Shell
 * ============================================
 * Handles all bookmarklet POST requests. Delegates all logic to BibMan_Core.
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
    dashUrl:                   p.getProperty('BIBMAN_DASHBOARD_URL')       || '',
    // Version info — compared against version.json on GitHub by BibMan_Core
    bookmarkletCaptureVersion: parseInt(p.getProperty('BOOKMARKLET_CAPTURE_VERSION'), 10) || 1,
    linkedCoreVersion:         BibManCore.getCoreVersion(),
    frontendThinClientVersion: 1,  // capture webapp doesn't know thin client version; safe default
  };
}

// ── Web app entry point ────────────────────────────────────────────────────────
function doPost(e) { return BibManCore.captureDoPost(_cfg(), e); }
