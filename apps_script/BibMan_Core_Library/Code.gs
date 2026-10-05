/**
 * BibMan_Core  — GAS Library
 * ==========================
 * Central business logic for BibMan bibliographic management system.
 * Contains NO Script Properties reads and NO personal credentials.
 * All configuration is received via the `config` object passed by the
 * thin-client shell deployed by each research group.
 *
 * Config object shape (all fields optional, defaults to ''):
 * {
 *   credential:     string   // GAS_CREDENTIAL shared secret
 *   duckdnsUrl:     string   // primary tunnel, e.g. https://YOUR-SUBDOMAIN.duckdns.org
 *   cloudflareUrl:  string   // backup tunnel, auto-updated by VM
 *   adsToken:       string   // NASA ADS API token
 *   geminiKey:      string   // Google Gemini API key
 *   embedModel:     string   // default: 'models/gemini-embedding-001'
 *   generateModel:  string   // default: 'models/gemini-2.0-flash'
 *   pdfFolderId:    string   // Drive folder ID for BibMan_PDFs parent
 *   exportFolderId: string   // Drive folder ID for .bib exports (optional)
 *   cfWorkerUrl:    string   // Cloudflare Worker URL
 *   captureUrl:     string   // CAPTURE_WEBAPP_URL for bookmarklet
 *   accessSheetId:  string   // Spreadsheet ID containing allowed_users tab
 *   dashUrl:        string   // Dashboard URL for bookmarklet substitution
 * }
 *
 * Thin-client shell (what each group deploys) looks like:
 *
 *   function _cfg() {
 *     const p = PropertiesService.getScriptProperties();
 *     return {
 *       credential:    p.getProperty('GAS_CREDENTIAL')      || '',
 *       duckdnsUrl:    p.getProperty('DUCKDNS_URL')         || '',
 *       cloudflareUrl: p.getProperty('CLOUDFLARE_URL')      || '',
 *       adsToken:      p.getProperty('ADS_TOKEN')           || '',
 *       geminiKey:     p.getProperty('GEMINI_KEY')          || '',
 *       embedModel:    p.getProperty('EMBED_MODEL')         || 'models/gemini-embedding-001',
 *       generateModel: p.getProperty('GENERATE_MODEL')      || 'models/gemini-2.0-flash',
 *       pdfFolderId:   p.getProperty('PDF_FOLDER_ID')       || '',
 *       exportFolderId:p.getProperty('EXPORT_FOLDER_ID')    || '',
 *       cfWorkerUrl:   p.getProperty('CF_WORKER_URL')       || '',
 *       captureUrl:    p.getProperty('CAPTURE_WEBAPP_URL')  || '',
 *       accessSheetId: p.getProperty('ACCESS_SHEET_ID')     || '',
 *       dashUrl:       p.getProperty('BIBMAN_DASHBOARD_URL')
 *                        || ScriptApp.getService().getUrl(),
 *     };
 *   }
 *
 *   function doGet(e)          { return BibManCore.doGet(_cfg(), e); }
 *   function doPost(e)         { return BibManCore.doPost(_cfg(), e); }
 *   function gas(fn, ...args)  { return BibManCore.dispatch(_cfg(), fn, ...args); }
 *   function runNightlyCron()  { return BibManCore.runNightlyCron(_cfg()); }
 *   function setupCronTrigger(){ return BibManCore.setupCronTrigger(); }
 *
 * Architecture:
 *   Browser → script.google.com (thin client) → BibMan_Core (this library)
 *           → YOUR-SUBDOMAIN.duckdns.org → nginx:8080 → Flask:8081 → SQLite
 */
// ═══════════════════════════════════════════════════════════════════════════════
// ── 0. VERSION CONSTANTS  (add near top of BibMan_Core.gs) ───────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// Bump BIBMAN_CORE_LIBRARY_VERSION each time you publish a new BibMan_Core library version.
// Bump FRONTEND_THINCLIENT_VERSION each time Index.html needs to be updated by groups.
// Bump BOOKMARKLET_CAPTURE_VERSION each time the capture webapp thin client needs to be updated.
// All three numbers are checked against version.json on GitHub.
//   Core logic change:   bump BIBMAN_CORE_LIBRARY_VERSION + bibman_core_library_version in version.json
//   UI change:           bump FRONTEND_THINCLIENT_VERSION + bibman_frontend_thinclient_webapp_version in version.json
//   Capture webapp change:  bump BOOKMARKLET_CAPTURE_VERSION + bibman_bookmarklet_capture_webapp_version in version.json
/*
BIBMAN_CORE_LIBRARY_VERSION SHOULD BE PLACED IN THE SCRIPT PROPERTIES OF THIS FILE to represent the version of this library
*/
const BIBMAN_CORE_LIBRARY_VERSION = parseInt( PropertiesService.getScriptProperties().getProperty('BIBMAN_CORE_LIBRARY_VERSION'), 10) || 1;
// ═══════════════════════════════════════════════════════════════════════════════
// ── VERSION CHECK ─────────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// Fetches https://raw.githubusercontent.com/pmarcum/BibMan/main/version.json
// Fails silently — a GitHub outage means no update banners, not a broken app.
//
// version.json format:
// {
//   "bibman_core_library_version": 1,
//   "bibman_frontend_thinclient_webapp_version": 1,
//   "bibman_bookmarklet_capture_webapp_version": 1,
//   "bibman_core_library_notes": "What changed in BibMan_Core",
//   "bibman_frontend_thinclient_webapp_notes": "What changed in Index.html",
//   "bibman_bookmarklet_capture_webapp_notes": "What changed in the capture webapp thin client"
// }
// ═══════════════════════════════════════════════════════════════════════════════
// ── VERSION CHECK (PROPERTIES-DRIVEN) ──────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// Fetches https://raw.githubusercontent.com/pmarcum/BibMan/main/version.json
// Fails silently — a GitHub outage means no update banners, not a broken app.
function _checkForUpdates(frontendThinClientVersion, bookmarkletCaptureVersion, linkedCoreVersion) {
  try {
    const resp = UrlFetchApp.fetch(
      'https://raw.githubusercontent.com/pmarcum/BibMan/main/version.json?t=' + Date.now(),
      { muteHttpExceptions: true, deadline: 5 }
    );
    if (resp.getResponseCode() !== 200) return {};
    const v = JSON.parse(resp.getContentText());
    return {
      coreLibraryUpdateAvailable:
        (v.bibman_core_library_version || 0) > (linkedCoreVersion || BIBMAN_CORE_LIBRARY_VERSION),
      frontendThinClientUpdateAvailable:
        (v.bibman_frontend_thinclient_webapp_version || 0) > (frontendThinClientVersion || 1),
      bookmarkletCaptureUpdateAvailable:
        (v.bibman_bookmarklet_capture_webapp_version || 0) > (bookmarkletCaptureVersion || 1),
      coreLibraryNotes:        v.bibman_core_library_notes                    || '',
      frontendThinClientNotes: v.bibman_frontend_thinclient_webapp_notes      || '',
      bookmarkletCaptureNotes: v.bibman_bookmarklet_capture_webapp_version     || '',
      latestCoreLibrary:       v.bibman_core_library_version                  || 1,
      latestFrontendThinClient: v.bibman_frontend_thinclient_webapp_version   || 1,
      latestBookmarkletCapture: v.bibman_bookmarklet_capture_webapp_version   || 1,
    };
  } catch(e) {
    Logger.log('BibManCore._checkForUpdates: ' + e.message);
    return {};
  }
}

function getCoreVersion() { return BIBMAN_CORE_LIBRARY_VERSION; }

// ═══════════════════════════════════════════════════════════════════════════════
// ── 1. CONFIG RESOLUTION ──────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * resolveConfig: Accepts the raw config from the thin client, performs the
 * DuckDNS/Cloudflare health check, and returns a resolved config with
 * `tunnelUrl` and `baseUrl` set.
 *
 * Module-level cache — persists for the lifetime of one GAS execution.
 * Each browser gas() call is a separate execution, so this is always fresh.
 */
let _configCache = null;
function resolveConfig(config) {
  if (_configCache) return _configCache;
  const duckdnsUrl    = config.duckdnsUrl    || '';
  const cloudflareUrl = config.cloudflareUrl || '';
  let tunnelUrl = '';
  // Try DuckDNS first — primary, stable, unlimited bandwidth
  if (duckdnsUrl) {
    try {
      const resp = UrlFetchApp.fetch(duckdnsUrl + '/health', {
        muteHttpExceptions: true,
        deadline: 5,
      });
      const code = resp.getResponseCode();
      const body = resp.getContentText();
      // Must return valid JSON with status:healthy — bandwidth error pages won't match
      if (code === 200 && body.includes('"status"') && body.includes('"healthy"')) {
        tunnelUrl = duckdnsUrl;
      }
    } catch(e) {}
  }
  // Fall back to Cloudflare if DuckDNS failed
  if (!tunnelUrl && cloudflareUrl) {
    try {
      const resp = UrlFetchApp.fetch(cloudflareUrl + '/health', {
        muteHttpExceptions: true,
        deadline: 5,
      });
      const code = resp.getResponseCode();
      const body = resp.getContentText();
      if (code === 200 && body.includes('"status"') && body.includes('"healthy"')) {
        tunnelUrl = cloudflareUrl;
      }
    } catch(e) {}
  }
  // Last resort — use whatever URL exists
  if (!tunnelUrl) tunnelUrl = duckdnsUrl || cloudflareUrl;
  _configCache = Object.assign({}, config, {
    tunnelUrl: tunnelUrl,
    // All BibMan API calls are namespaced under /bibman/ by Nginx.
    // Nginx strips the prefix before forwarding to Flask on port 8081.
    baseUrl:      tunnelUrl + '/bibman',
    embedModel:   config.embedModel    || 'models/gemini-embedding-001',
    generateModel:config.generateModel || 'models/gemini-2.0-flash',
  });
  return _configCache;
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 2. CLIENT CONFIG (returned to browser) ────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * getClientConfig: Returns the subset of config that the browser dashboard
 * needs: baseUrl, credential, geminiKey, current user info, admin flag.
 * Has version check so Index.html can show update banners
 */
function getClientConfig(config) {
  const resolved = resolveConfig(config);
  const email    = Session.getActiveUser().getEmail();
  const users    = getAllowedUsers(config);
  const me       = users.find(u => u.email === email.toLowerCase());
  const updates  = _checkForUpdates(
    config.frontendThinClientVersion  || 1,
    config.bookmarkletCaptureVersion  || 1,
    config.linkedCoreVersion          || BIBMAN_CORE_LIBRARY_VERSION
  );
  return {
    baseUrl:                           resolved.baseUrl,
    credential:                        resolved.credential,
    geminiKey:                         resolved.geminiKey,
    currentUser:                       email ? email.split('@')[0] : '',
    currentUserEmail:                  email || '',
    isAdmin:                           me ? me.is_admin : false,
    coreLibraryVersion:                config.linkedCoreVersion || BIBMAN_CORE_LIBRARY_VERSION,
    frontendThinClientVersion:         config.frontendThinClientVersion || 1,
    bookmarkletCaptureVersion:         config.bookmarkletCaptureVersion || 1,
    coreLibraryUpdateAvailable:        updates.coreLibraryUpdateAvailable        || false,
    frontendThinClientUpdateAvailable: updates.frontendThinClientUpdateAvailable || false,
    bookmarkletCaptureUpdateAvailable: updates.bookmarkletCaptureUpdateAvailable || false,
    coreLibraryNotes:                  updates.coreLibraryNotes                  || '',
    frontendThinClientNotes:           updates.frontendThinClientNotes           || '',
    bookmarkletCaptureNotes:           updates.bookmarkletCaptureNotes           || '',
    latestCoreLibrary:                 updates.latestCoreLibrary                 || BIBMAN_CORE_LIBRARY_VERSION,
    latestFrontendThinClient:          updates.latestFrontendThinClient          || 1,
    latestBookmarkletCapture:          updates.latestBookmarkletCapture          || 1,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 3. DISPATCH (called by thin-client gas() function) ────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * dispatch: Routes a named function call from Index.html → BibMan_Core.
 *
 * The thin client exposes exactly one function to the browser:
 *   function gas(fn, ...args) { return BibManCore.dispatch(_cfg(), fn, ...args); }
 *
 * Index.html calls it like:
 *   google.script.run.gas('getPapers', library, everyone)
 *
 * All functions in the dispatch table receive (config, ...args).
 * Adding a new API function only requires adding it here — thin client never changes.
 */
function dispatch(config, fn, ...args) {
  const table = {
    // Config / user
    getClientConfig:       () => getClientConfig(config),
    getCfWorkerUrl:        () => getCfWorkerUrl(config),
    // Access control
    getAllowedUsers:        () => getAllowedUsers(config),
    // Libraries
    getLibraries:          () => getLibraries(config),
    getCurrentLibrary:     () => getCurrentLibrary(config),
    switchLibrary:         (name) => switchLibrary(config, name),
    createLibrary:         (name) => createLibrary(config, name),
    deleteLibrary:         (id) => deleteLibrary(config, id),
    // Papers
    getPapers:             (library, everyone) => getPapers(config, library, everyone),
    getPaper:              (paperId, everyone) => getPaper(config, paperId, everyone),
    updatePaper:           (paperId, data) => updatePaper(config, paperId, data),
    deletePaper:           (paperId) => deletePaper(config, paperId),
    updateReadStatus:      (paperId, s) => updateReadStatus(config, paperId, s),
    updateBibtex:          (paperId, bib) => updateBibtex(config, paperId, bib),
    setPdfSource:          (paperId, u, f) => setPdfSource(config, paperId, u, f),
    getIngestStatus:       (paperId) => getIngestStatus(config, paperId),
    rerunIngest:           (paperId) => rerunIngest(config, paperId),
    bulkReextract:         (all, library) => bulkReextract(config, all, library),
    addPaperByIdentifier:  (identifier, library) => addPaperByIdentifier(config, identifier, library),
    addPaperManual:        (data) => addPaperManual(config, data),
    importBib:             (bibContent, library) => importBib(config, bibContent, library),
    // ADS search
    lookupPaperByIdentifier: (identifier) => lookupPaperByIdentifier(config, identifier),
    searchAdsByTitle:        (title) => searchAdsByTitle(config, title),
    // Search
    vennSearch:            (queries, globalExcludes, library) => vennSearch(config, queries, globalExcludes, library),
    searchSuggestions:     (q) => searchSuggestions(config, q),
    // Annotations
    createAnnotation:      (data) => createAnnotation(config, data),
    updateAnnotation:      (id, data) => updateAnnotation(config, id, data),
    deleteAnnotation:      (id) => deleteAnnotation(config, id),
    updateAnnotationFlags: (id, f) => updateAnnotationFlags(config, id, f),
    // Synonyms
    getSynonyms:           () => getSynonyms(config),
    addSynonym:            (a, b) => addSynonym(config, a, b),
    approveSynonym:        (id) => approveSynonym(config, id),
    deleteSynonym:         (id) => deleteSynonym(config, id),
    importDefaultSynonyms: () => importDefaultSynonyms(config),
    // Annotated papers / config / status
    getAnnotatedPapers:    () => getAnnotatedPapers(config),
    getConfig_:            () => getConfig_(config),
    updateConfig:          (data) => updateConfig(config, data),
    getStatus:             () => getStatus(config),
    // Export / import
    exportBibTodrive:      (library) => exportBibTodrive(config, library),
    exportBibText:         (library) => exportBibText(config, library),
    exportBib:             (bibkeys, library) => exportBib(config, bibkeys, library),
    // PDF delivery
    getPdfInfo:            (paperId) => getPdfInfo(config, paperId),
    getDrivePdfUrl:        (fileId) => getDrivePdfUrl(fileId),
    getDrivePdfBase64:     (fileId) => getDrivePdfBase64(fileId),
    getProxyPdfBase64:     (paperId) => getProxyPdfBase64(config, paperId),
    // Bookmarklet
    getBookmarkletCode:    () => getBookmarkletCode(config),
    // Mentions
    createMention:         (data) => createMention(config, data),
    getUnreadMentions:     () => getUnreadMentions(config),
    markMentionSeen:       (id) => markMentionSeen(config, id),
    markAllMentionsSeen:   () => markAllMentionsSeen(config),
    getMentionCount:       () => getMentionCount(config),
    // Team
    getTeam:               () => getTeam(config),
    addTeamMember:         (username) => addTeamMember(config, username),
    removeTeamMember:      (id) => removeTeamMember(config, id),
    // Embeddings
    backfillEmbeddings:    (paperId) => backfillEmbeddings(config, paperId),
    getBackfillList:       (library) => getBackfillList(config, library),
    // Tags
    getTagLabels:          (everyone) => getTagLabels(config, everyone),
    createTagLabel:        (label, color) => createTagLabel(config, label, color),
    updateTagLabel:        (id, label, color) => updateTagLabel(config, id, label, color),
    deleteTagLabel:        (id) => deleteTagLabel(config, id),
    getPaperTags:          (paperId, everyone) => getPaperTags(config, paperId, everyone),
    addPaperTag:           (paperId, labelId, annotationId) => addPaperTag(config, paperId, labelId, annotationId),
    removePaperTag:        (paperId, labelId, annotationId) => removePaperTag(config, paperId, labelId, annotationId),
    getTaggedPapers:       (labelIds, everyone) => getTaggedPapers(config, labelIds, everyone),
  };
  if (!table[fn]) throw new Error(`BibManCore.dispatch: unknown function "${fn}"`);
  return table[fn](...args);
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 4. WEB APP ENTRY POINTS ───────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * doGet: Access-control check then serve the BibMan dashboard HTML.
 * Called by the thin client's doGet(e) → BibManCore.doGet(config, e).
 *
 * Index.html is fetched from GitHub at serve time so all groups always
 * get the latest UI without redeploying their thin client.
 */
function doGet(config, e) {
  const email   = Session.getActiveUser().getEmail();
  const users   = getAllowedUsers(config);
  const allowed = users.map(u => u.email);
  if (!allowed.includes(email.toLowerCase())) {
    return HtmlService.createHtmlOutput(
      '<h3 style="font-family:monospace;color:#f77e7e">Access denied.</h3>' +
      '<p style="font-family:monospace">Your account (' + email + ') is not authorized for BibMan.</p>'
    ).setTitle('BibMan — Access Denied');
  }
  // Fetch Index.html from GitHub so UI updates don't require thin-client redeployment.
  // Falls back to a bundled minimal page if GitHub is unreachable.
  let htmlContent;
  try {
    const resp = UrlFetchApp.fetch('https://raw.githubusercontent.com/pmarcum/BibMan/main/Index.html?t=' + Date.now(),
      { muteHttpExceptions: true, deadline: 10 } );
    if (resp.getResponseCode() === 200) {
      htmlContent = resp.getContentText();
    }
  } catch(err) {
    Logger.log('BibManCore.doGet: GitHub fetch failed: ' + err.message);
  }
  if (!htmlContent) {
    // Fallback: minimal error page — user should check VM connectivity
    return HtmlService.createHtmlOutput(
      '<h3 style="font-family:monospace;color:#f7c77e">BibMan UI temporarily unavailable.</h3>' +
      '<p style="font-family:monospace">Could not fetch dashboard from GitHub. Please try again shortly.</p>'
    ).setTitle('BibMan');
  }
  return HtmlService.createHtmlOutput(htmlContent)
    .setTitle('BibMan')
    .setFaviconUrl('https://raw.githubusercontent.com/pmarcum/BibMan/main/favicon.png')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * doPost: Handles server-side POST actions (tunnel URL update, PDF upload).
 * Called by the thin client's doPost(e) → BibManCore.doPost(config, e).
 */
function doPost(config, e) {
  try {
    const data = JSON.parse(e.postData.contents);
    // ── Tunnel URL update from VM ──────────────────────────────────────────
    // NOTE: This action updates a Script Property, so it must write via the
    // thin client's PropertiesService. We return a special sentinel object
    // and the thin client handles the actual property write.
    // See thin-client doPost() for the write side.
    if (data.action === 'update_tunnel_url') {
      if (data.credential !== config.credential) {
        return ContentService.createTextOutput(
          JSON.stringify({ ok: false, error: 'unauthorized' })
        ).setMimeType(ContentService.MimeType.JSON);
      }
      // Signal thin client to write the new Cloudflare URL to Script Properties.
      // The thin client doPost() checks for _action: 'write_cloudflare_url'.
      // We can't write Script Properties from a Library directly — only the
      // bound script can do that.
      return { _action: 'write_cloudflare_url', url: data.url || '' };
    }
    // ── PDF upload from VM (bypasses service account quota) ───────────────
    if (data.action === 'upload_pdf') {
      if (data.credential !== config.credential) {
        return ContentService.createTextOutput(
          JSON.stringify({ ok: false, error: 'unauthorized' })
        ).setMimeType(ContentService.MimeType.JSON);
      }
      try {
        const result = savePdfToDrive(config, data.pdf_base64, data.filename, data.library_name || '');
        return ContentService.createTextOutput(JSON.stringify(result))
          .setMimeType(ContentService.MimeType.JSON);
      } catch(err) {
        return ContentService.createTextOutput(
          JSON.stringify({ ok: false, error: err.message })
        ).setMimeType(ContentService.MimeType.JSON);
      }
    }
    return ContentService.createTextOutput(
      JSON.stringify({ ok: false, error: 'unknown action' })
    ).setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService.createTextOutput(
      JSON.stringify({ error: err.message })
    ).setMimeType(ContentService.MimeType.JSON);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 5. CORE PROXY ─────────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * apiCall: Proxy an API request to the Flask backend via DuckDNS or Cloudflare.
 * Injects BYOK headers on every request.
 */
function apiCall(config, method, path, body, params) {
  const resolved = resolveConfig(config);
  if (!resolved.tunnelUrl) { throw new Error('No tunnel URL configured (duckdnsUrl or cloudflareUrl missing from config)'); }
  let url = resolved.baseUrl + path;
  if (params) {
    const qs = Object.entries(params)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join('&');
    url += '?' + qs;
  }
  const options = {
    method:      method.toLowerCase(),
    contentType: 'application/json',
    headers: {
      'X-BibMan-Credential': resolved.credential,
      'X-BibMan-User':       (() => { try { return Session.getActiveUser().getEmail() || ''; } catch(e) { return ''; } })(),
      'X-GAS-Webapp-URL':    config.dashUrl || ScriptApp.getService().getUrl(),
      'X-ADS-Token':         resolved.adsToken      || '',
      'X-Gemini-Key':        resolved.geminiKey     || '',
      'X-Embed-Model':       resolved.embedModel,
      'X-Generate-Model':    resolved.generateModel,
    },
    muteHttpExceptions: true,
    followRedirects:    true,
    deadline:           55,
  };
  if (body && ['POST', 'PATCH', 'PUT'].includes(method.toUpperCase())) { options.payload = JSON.stringify(body); }
  try {
    const response = UrlFetchApp.fetch(url, options);
    const code     = response.getResponseCode();
    const text     = response.getContentText();
    if (code >= 400) {
      let errMsg = `HTTP ${code}`;
      try { errMsg = JSON.parse(text).error || errMsg; } catch(e) {}
      throw new Error(errMsg);
    }
    try   { return JSON.parse(text); }
    catch { return { raw: text }; }
  } catch(err) {
    Logger.log(`BibManCore.apiCall error ${method} ${path}: ${err.message}`);
    throw err;
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 6. ACCESS CONTROL ─────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
function getAllowedUsers(config) {
  try {
    const sheetId = config.accessSheetId || '';
    if (!sheetId) return [];
    const ss  = SpreadsheetApp.openById(sheetId);
    const tab = ss.getSheetByName('allowed_users');
    if (!tab) return [];
    const data = tab.getDataRange().getValues();
    return data.slice(1)
      .filter(row => row[0] && row[1])
      .map(row => ({
        email:    row[0].toString().trim().toLowerCase(),
        name:     row[1].toString().trim(),
        is_admin: row[3] === true || row[3].toString().toLowerCase() === 'true',
      }));
  } catch(err) {
    Logger.log('BibManCore.getAllowedUsers error: ' + err.message);
    return [];
  }
}

/**
 * fetchDashboardHtml: Fetches the BibMan dashboard UI from GitHub.
 * 
 * Index.html lives on GitHub rather than in each group's GAS project so that
 * UI updates are delivered instantly to all deployed instances without any
 * redeployment. Every doGet() call fetches a fresh copy with a cache-busting
 * timestamp parameter.
 *
 * Returns the HTML content as a string on success, or a minimal fallback
 * error page if GitHub is unreachable. The thin client is responsible for
 * injecting the logo (<!--LOGO_PLACEHOLDER-->) and serving via HtmlService —
 * GAS libraries cannot serve HtmlService output directly.
 */
function fetchDashboardHtml() {
  const url = 'https://raw.githubusercontent.com/pmarcum/BibMan/main/Index.html?t=' + Date.now();
  try {
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true, deadline: 10 });
    if (resp.getResponseCode() === 200) return resp.getContentText();
  } catch(err) {
    Logger.log('BibManCore.fetchDashboardHtml: ' + err.message);
  }
  return '<html><body style="font-family:monospace;padding:2em;">' +
    '<h3 style="color:#f77e7e">BibMan dashboard temporarily unavailable</h3>' +
    '<p>Could not fetch the dashboard from GitHub. Please try again in a moment.</p>' +
    '</body></html>';
}

function getAuthSuccessHtml() {
  return '<html><body style="font-family:monospace;background:#17171a;color:#e8e8f0;' +
    'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">' +
    '<div style="text-align:center;padding:40px">' +
    '<div style="font-size:48px;margin-bottom:16px">✅</div>' +
    '<h2 style="color:#7eb8f7;margin-bottom:12px">Authorization complete!</h2>' +
    '<p style="color:#888;line-height:1.6">You can close this tab and refresh BibMan.</p>' +
    '</div></body></html>';
}

function getAccessDeniedHtml(email) {
  return '<h3 style="font-family:monospace;color:#f77e7e">Access denied.</h3>' +
    '<p style="font-family:monospace">Your account (' + (email || '') + ') is not authorized for BibMan.</p>';
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 7. ADS API (runs entirely in GAS — never hits the VM) ────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
const ADS_SEARCH_URL = 'https://api.adsabs.harvard.edu/v1/search/query';
const ADS_FIELDS     = 'bibcode,title,author,year,pub,volume,page,identifier,doi,abstract,pubdate,doctype,bibtex';

/**
 * lookupPaperByIdentifier: Resolve a DOI, arXiv ID, or ADS bibcode via ADS.
 * Returns a clean paper object ready to POST to /api/papers/add-manual,
 * or null if not found.
 */
function lookupPaperByIdentifier(config, identifier) {
  if (!config.adsToken) throw new Error('adsToken not provided in config');
  const url = `${ADS_SEARCH_URL}?q=${encodeURIComponent(identifier)}&fl=${ADS_FIELDS}&rows=1`;
  const options = {
    method:  'get',
    headers: { 'Authorization': `Bearer ${config.adsToken}` },
    muteHttpExceptions: true,
    deadline: 20,
  };
  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() !== 200) {
    throw new Error(`ADS returned HTTP ${response.getResponseCode()}`);
  }
  const docs = JSON.parse(response.getContentText()).response?.docs || [];
  if (!docs.length) return null;
  return _adsDocToPaper(docs[0]);
}

/**
 * searchAdsByTitle: Search ADS by title, return top 5 results.
 */
function searchAdsByTitle(config, title) {
  if (!config.adsToken) throw new Error('adsToken not provided in config');
  const url = `${ADS_SEARCH_URL}?q=${encodeURIComponent('title:' + title)}&fl=${ADS_FIELDS}&rows=5`;
  const options = {
    method:  'get',
    headers: { 'Authorization': `Bearer ${config.adsToken}` },
    muteHttpExceptions: true,
    deadline: 20,
  };
  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() !== 200) { throw new Error(`ADS returned HTTP ${response.getResponseCode()}`); }
  const docs = JSON.parse(response.getContentText()).response?.docs || [];
  return { count: docs.length, results: docs.map(_adsDocToPaper) };
}

/**
 * addPaperByIdentifier: Full flow — ADS lookup then POST to backend.
 */
function addPaperByIdentifier(config, identifier, library) {
  const paper = lookupPaperByIdentifier(config, identifier);
  if (!paper) throw new Error(`No paper found for: ${identifier}`);
  if (library) paper.library = library;
  return apiCall(config, 'POST', '/api/papers/add-manual', paper);
}

/**
 * _adsDocToPaper: Map a raw ADS document to a clean BibMan paper payload.
 * Applies journal macro normalisation here in GAS.
 */
function _adsDocToPaper(doc) {
  const authors     = (doc.author || []).join(' and ');
  const identifiers = doc.identifier || [];
  const arxivId     = identifiers.find(i => i.toLowerCase().startsWith('arxiv:'))
                        ?.replace(/^arXiv:/i, '') || '';
  const doi         = (doc.doi || [])[0] || '';
  const pages       = (doc.page || [])[0] || '';
  const title       = (doc.title || [])[0] || '';
  const journal     = normalizeJournalToMacro(doc.pub || '');
  const vol         = doc.volume || '';
  const page1       = pages ? pages.toString().split(/[-–]/)[0] : '';
  const pubtype     = (doc.doctype || 'article').toLowerCase();
  const firstAuthor = (authors.split(';')[0].split(',')[0]).trim()
                        .normalize('NFD')
                        .replace(/[\u0300-\u036f]/g, '')
                        .toLowerCase().replace(/[^a-z]/g, '');
  const hasMultipleAuthors = (doc.author || []).length > 1;
  // ── Journal short form ────────────────────────────────────────────────────
  function journalToShort(j) {
    if (!j) return '';
    if (j.trim().startsWith('\\')) return j.trim().replace(/^\\/, '').toLowerCase();
    const normalized = normalizeJournalToMacro(j);
    if (normalized && normalized.startsWith('\\')) return normalized.replace(/^\\/, '').toLowerCase();
    const fillers = new Set(['of', 'the', 'and', 'in', 'for', 'a', 'an', 'on', 'to', '&']);
    const words = j.replace(/[^a-zA-Z\s]/g, '').trim().split(/\s+/)
                   .filter(w => w.length > 0 && !fillers.has(w.toLowerCase()));
    let short;
    if (words.length >= 4)      short = words.map(w => w[0]).join('').toLowerCase();
    else if (words.length >= 2) short = words.map(w => w.slice(0, 2)).join('').toLowerCase();
    else if (words.length === 1) short = words[0].slice(0, 4).toLowerCase();
    else                         short = 'misc';
    const knownMacros = new Set([
      'apj', 'apjs', 'apjl', 'aj', 'mnras', 'aap', 'aaps', 'araa', 'pasp', 'pasj',
      'pasa', 'nat', 'sci', 'icar', 'ssr', 'solphys', 'apss', 'prl', 'prd', 'jcap',
      'planss', 'aac',
    ]);
    if (knownMacros.has(short)) short = 'x' + short;
    return short;
  }
  // ── Publication type suffix when no journal ───────────────────────────────
  function pubtypeSuffix(dt) {
    const map = {
      'article':       '',
      'inproceedings': 'inproceedings',
      'proceedings':   'inproceedings',
      'book':          'book',
      'booklet':       'book',
      'inbook':        'book',
      'incollection':  'book',
      'bookchapter':   'book',
      'phdthesis':     'phd',
      'mastersthesis': 'msc',
      'techreport':    'tech',
      'manual':        'misc',
      'unpublished':   'misc',
      'misc':          'misc',
      'erratum':       'misc',
      'eprint':        'misc',
      'abstract':      'misc',
      'software':      'software',
      'dataset':       'data',
      'webpage':       'misc',
    };
    return map[dt] || 'misc';
  }
  // ── Assemble bibkey ───────────────────────────────────────────────────────
  const jshort = journalToShort(journal);
  let bibkey = firstAuthor;
  if (hasMultipleAuthors) bibkey += '+';
  bibkey += (doc.year || '');
  if (jshort && vol && page1)  bibkey += jshort + vol + '_' + page1;
  else if (jshort && vol)      bibkey += jshort + vol;
  else if (jshort)             bibkey += jshort;
  else                         bibkey += pubtypeSuffix(pubtype);
  bibkey = bibkey.replace(/\s+/g, '');
  return {
    bibkey:      bibkey,
    bibcode:     doc.bibcode  || '',
    title:       unicodeToLatex(title),
    authors:     unicodeToLatex(authors),
    year:        String(doc.year || ''),
    journal:     unicodeToLatex(journal),
    volume:      vol,
    pages:       pages,
    doi:         doi,
    abstract:    (doc.abstract || ''),
    bibtex:      unicodeToLatex(doc.bibtex || ''),
    pubtype:     pubtype,
    pdf_url:     arxivId ? `https://arxiv.org/pdf/${arxivId}` : '',
    identifiers: identifiers,
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 8. JOURNAL / UNICODE UTILITIES ───────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// Standard AASTeX macros. Applied before sending paper data to backend.
const JOURNAL_PATTERNS = [
  // ── Astrophysical Journal Supplement Series ──────────────────────────────
  [/^(?:the\s+)?a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:a(?:l)?)?)?)?)?)?)?)?)?)?)?)\s+j(?:o(?:u(?:r(?:n(?:a(?:l)?)?)?)?)?)?\s+s(?:u(?:p(?:p(?:l(?:e(?:m(?:e(?:n(?:t)?)?)?)?)?)?)?)?)?/i, '\\apjs'],
  [/^\\?apjs$/i, '\\apjs'],
  // ── Astrophysical Journal Letters ────────────────────────────────────────
  [/^(?:the\s+)?a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:a(?:l)?)?)?)?)?)?)?)?)?)?)?)\s+j(?:o(?:u(?:r(?:n(?:a(?:l)?)?)?)?)?)?\s+l(?:e(?:t(?:t(?:e(?:r(?:s?)?)?)?)?)?)?/i, '\\apjl'],
  [/^\\?apjl$/i, '\\apjl'],
  // ── Astrophysical Journal (bare) ─────────────────────────────────────────
  [/^(?:the\s+)?a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:a(?:l)?)?)?)?)?)?)?)?)?)?)?)\s+j(?:o(?:u(?:r(?:n(?:a(?:l)?)?)?)?)?)?$/i, '\\apj'],
  [/^\\?apj$/i, '\\apj'],
  // ── Astronomical Journal ─────────────────────────────────────────────────
  [/^(?:the\s+)?a(?:s(?:t(?:r(?:o(?:n(?:o(?:m(?:i(?:c(?:a(?:l)?)?)?)?)?)?)?)?)?)?)\s+j(?:o(?:u(?:r(?:n(?:a(?:l)?)?)?)?)?)?$/i, '\\aj'],
  [/^\\?aj$/i, '\\aj'],
  // ── Monthly Notices of the Royal Astronomical Society ────────────────────
  [/^m(?:o(?:n(?:t(?:h(?:l(?:y)?)?)?)?)?)?\s+n(?:o(?:t(?:i(?:c(?:e(?:s?)?)?)?)?)?)?/i, '\\mnras'],
  [/^\\?mnras$/i, '\\mnras'],
  // ── Astronomy and Astrophysics Supplement ────────────────────────────────
  [/^a(?:s(?:t(?:r(?:o(?:n(?:o(?:m(?:y)?)?)?)?)?)?)?)\s+(?:&|and)\s+a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:s?)?)?)?)?)?)?)?)?)?)?)\s+s(?:u(?:p(?:p?)?)?)?/i, '\\aaps'],
  // ── Astronomy and Astrophysics ───────────────────────────────────────────
  [/^a(?:s(?:t(?:r(?:o(?:n(?:o(?:m(?:y)?)?)?)?)?)?)?)\s+(?:&|and)\s+a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:s?)?)?)?)?)?)?)?)?)?)?)?$/i, '\\aap'],
  [/^\\?aap?$/i, '\\aap'],
  // ── Annual Review of Astronomy and Astrophysics ──────────────────────────
  [/^a(?:n(?:n(?:u(?:a(?:l)?)?)?)?)?\s+r(?:e(?:v(?:i(?:e(?:w)?)?)?)?)?\s+.*a(?:s(?:t(?:r(?:o(?:n?)?)?)?)?)?/i, '\\araa'],
  [/^\\?araa$/i, '\\araa'],
  // ── Publications of the ASP ──────────────────────────────────────────────
  [/^p(?:u(?:b(?:l(?:i(?:c(?:a(?:t(?:i(?:o(?:n(?:s?)?)?)?)?)?)?)?)?)?)?)\s+.*p(?:a(?:c(?:i(?:f(?:i(?:c?)?)?)?)?)?)?$/i, '\\pasp'],
  [/^\\?pasp$/i, '\\pasp'],
  // ── Publications of the ASJ ──────────────────────────────────────────────
  [/^p(?:u(?:b(?:l(?:i(?:c(?:a(?:t(?:i(?:o(?:n(?:s?)?)?)?)?)?)?)?)?)?)?)\s+.*j(?:a(?:p(?:a(?:n?)?)?)?)?$/i, '\\pasj'],
  [/^\\?pasj$/i, '\\pasj'],
  // ── Publications of the ASA ──────────────────────────────────────────────
  [/^p(?:u(?:b(?:l(?:i(?:c(?:a(?:t(?:i(?:o(?:n(?:s?)?)?)?)?)?)?)?)?)?)?)\s+.*a(?:u(?:s(?:t(?:r(?:a(?:l(?:i(?:a?)?)?)?)?)?)?)?)?$/i, '\\pasa'],
  [/^\\?pasa$/i, '\\pasa'],
  // ── Nature Astronomy ─────────────────────────────────────────────────────
  [/^nat(?:ure)?\s+astron/i, '\\nat'],
  // ── Nature (bare) ────────────────────────────────────────────────────────
  [/^nat(?:ure)?$/i, '\\nat'],
  // ── Science ──────────────────────────────────────────────────────────────
  [/^sci(?:ence)?$/i, '\\sci'],
  // ── Icarus ───────────────────────────────────────────────────────────────
  [/^ic(?:a(?:r(?:u(?:s)?)?)?)?$/i, '\\icar'],
  // ── Space Science Reviews ─────────────────────────────────────────────────
  [/^sp(?:a(?:c(?:e)?)?)?\s+sci(?:ence)?\s+rev/i, '\\ssr'],
  [/^\\?ssr$/i, '\\ssr'],
  // ── Solar Physics ────────────────────────────────────────────────────────
  [/^sol(?:ar)?\s+ph(?:y(?:s(?:i(?:c(?:s?)?)?)?)?)?$/i, '\\solphys'],
  // ── Astrophysics and Space Science ───────────────────────────────────────
  [/^a(?:s(?:t(?:r(?:o(?:p(?:h(?:y(?:s(?:i(?:c(?:s?)?)?)?)?)?)?)?)?)?)?)\s+(?:&|and)\s+sp(?:a(?:c(?:e?)?)?)?\s+sci(?:ence)?/i, '\\apss'],
  [/^\\?apss$/i, '\\apss'],
  // ── Physical Review Letters ───────────────────────────────────────────────
  [/^ph(?:y(?:s(?:i(?:c(?:a(?:l)?)?)?)?)?)?\s+r(?:e(?:v(?:i(?:e(?:w)?)?)?)?)?\s+l(?:e(?:t(?:t)?)?)?/i, '\\prl'],
  [/^\\?prl$/i, '\\prl'],
  // ── Physical Review D ─────────────────────────────────────────────────────
  [/^ph(?:y(?:s(?:i(?:c(?:a(?:l)?)?)?)?)?)?\s+r(?:e(?:v(?:i(?:e(?:w)?)?)?)?)?\s+d$/i, '\\prd'],
  [/^\\?prd$/i, '\\prd'],
  // ── JCAP ─────────────────────────────────────────────────────────────────
  [/^j(?:o(?:u(?:r(?:n(?:a(?:l)?)?)?)?)?)?\s+.*c(?:o(?:s(?:m(?:o(?:l?)?)?)?)?)?.*\s+ph(?:y(?:s?)?)?/i, '\\jcap'],
  [/^\\?jcap$/i, '\\jcap'],
  // ── Planetary and Space Science ───────────────────────────────────────────
  [/^pl(?:a(?:n(?:e(?:t(?:a(?:r(?:y)?)?)?)?)?)?)?\s+.*\s+sp(?:a(?:c(?:e?)?)?)?/i, '\\planss'],
  // ── Astronomy and Computing ───────────────────────────────────────────────
  [/^a(?:s(?:t(?:r(?:o(?:n(?:o(?:m(?:y)?)?)?)?)?)?)?)\s+.*\s+comp(?:u(?:t(?:i(?:n(?:g?)?)?)?)?)?/i, '\\aac'],
  // ── arXiv — no macro, return as-is ───────────────────────────────────────
  [/^ar[xX]iv/i, null],
];
function normalizeJournalToMacro(journal) {
  if (!journal) return journal;
  const s = journal.trim().replace(/[{}]/g, '').trim();
  if (s.startsWith('\\')) return s;
  for (const [pattern, macro] of JOURNAL_PATTERNS) {
    if (pattern.test(s)) return macro || s;
  }
  return s;
}

function unicodeToLatex(s) {
  if (!s) return s;
  const map = {
    'à': "\\`{a}", 'á': "\\'{a}", 'â': "\\^{a}", 'ã': "\\~{a}", 'ä': '\\"{a}', 'å': '{\\aa}',
    'è': "\\`{e}", 'é': "\\'{e}", 'ê': "\\^{e}", 'ë': '\\"{e}',
    'ì': "\\`{i}", 'í': "\\'{i}", 'î': "\\^{i}", 'ï': '\\"{i}',
    'ò': "\\`{o}", 'ó': "\\'{o}", 'ô': "\\^{o}", 'õ': "\\~{o}", 'ö': '\\"{o}', 'ø': '{\\o}',
    'ù': "\\`{u}", 'ú': "\\'{u}", 'û': "\\^{u}", 'ü': '\\"{u}',
    'ý': "\\'{y}", 'ÿ': '\\"{y}',
    'ñ': "\\~{n}", 'ç': "\\c{c}",
    'À': "\\`{A}", 'Á': "\\'{A}", 'Â': "\\^{A}", 'Ã': "\\~{A}", 'Ä': '\\"{A}', 'Å': '{\\AA}',
    'È': "\\`{E}", 'É': "\\'{E}", 'Ê': "\\^{E}", 'Ë': '\\"{E}',
    'Ì': "\\`{I}", 'Í': "\\'{I}", 'Î': "\\^{I}", 'Ï': '\\"{I}',
    'Ò': "\\`{O}", 'Ó': "\\'{O}", 'Ô': "\\^{O}", 'Õ': "\\~{O}", 'Ö': '\\"{O}', 'Ø': '{\\O}',
    'Ù': "\\`{U}", 'Ú': "\\'{U}", 'Û': "\\^{U}", 'Ü': '\\"{U}',
    'Ñ': "\\~{N}", 'Ç': "\\c{C}",
  };
  return s.replace(/[^\x00-\x7F]/g, c => map[c] || c);
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 9. PDF DELIVERY ───────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
function getPdfInfo(config, paperId) { return apiCall(config, 'GET', `/api/papers/${paperId}/pdf-info`); }

/**
 * getDrivePdfUrl: Returns an OAuth token the browser uses to fetch a Drive PDF
 * directly from googleapis.com (GAS is not in the bytes path — fast).
 */
function getDrivePdfUrl(fileId) { return ScriptApp.getOAuthToken(); }

function getDrivePdfBase64(fileId) {
  try {
    const file  = DriveApp.getFileById(fileId);
    const bytes = file.getBlob().getBytes();
    if (bytes.length > 37.5 * 1024 * 1024) {
      throw new Error(`PDF too large (${Math.round(bytes.length / 1024 / 1024)}MB > 37.5MB limit)`);
    }
    return Utilities.base64Encode(bytes);
  } catch(err) {
    Logger.log(`BibManCore.getDrivePdfBase64 error: ${err.message}`);
    throw err;
  }
}

function getProxyPdfBase64(config, paperId) {
  const resolved = resolveConfig(config);
  const url      = `${resolved.baseUrl}/api/papers/${paperId}/pdf`;
  const options  = {
    method:  'get',
    headers: {
      'X-BibMan-Credential': resolved.credential,
      'X-BibMan-User':       Session.getActiveUser().getEmail(),
    },
    muteHttpExceptions: true,
    deadline: 33,
  };
  const response = UrlFetchApp.fetch(url, options);
  if (response.getResponseCode() !== 200) { throw new Error(`PDF fetch failed: HTTP ${response.getResponseCode()}`); }
  const bytes = response.getContent();
  if (!bytes || bytes.length === 0) throw new Error('Empty PDF response');
  return Utilities.base64Encode(bytes);
}

function getCfWorkerUrl(config) { return config.cfWorkerUrl || ''; }

// ═══════════════════════════════════════════════════════════════════════════════
// ── 10. DRIVE / EXPORT ────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * exportBibTodrive: Fetch .bib content from VM and write/update a file in Drive.
 * Looks for an existing <library>.bib in exportFolderId (or Drive root).
 * Creates it if not found, overwrites in place if it exists.
 * Returns { ok, fileName, fileId, driveUrl }
 */
function exportBibTodrive(config, library) {
  const resolved = resolveConfig(config);
  const fileName = (library || 'library').toLowerCase().replace(/\s+/g, '_') + '.bib';
  // 1. Fetch bib content from VM
  const url = `${resolved.baseUrl}/api/export/bib-text?library=${encodeURIComponent(library || '')}`;
  const response = UrlFetchApp.fetch(url, {
    method:  'get',
    headers: { 'X-BibMan-Credential': resolved.credential },
    muteHttpExceptions: true,
    deadline: 55,
  });
  if (response.getResponseCode() !== 200) { throw new Error(`VM returned HTTP ${response.getResponseCode()}`); }
  const bibContent = response.getContentText();
  // 2. Determine target folder (root unless exportFolderId is set)
  const folder = config.exportFolderId
    ? DriveApp.getFolderById(config.exportFolderId)
    : DriveApp.getRootFolder();
  // 3. Find existing file or create new one
  const existingIter = folder.getFilesByName(fileName);
  let file;
  if (existingIter.hasNext()) {
    file = existingIter.next();
    file.setContent(bibContent);
  } else {
    file = folder.createFile(fileName, bibContent, 'text/plain');
  }
  return {
    ok:       true,
    fileName: fileName,
    fileId:   file.getId(),
    driveUrl: file.getUrl(),
  };
}

/**
 * savePdfToDrive: Called by Flask VM via doPost upload_pdf action.
 * Saves a PDF to BibMan_PDFs/<library_name>/<bibkey>.pdf in Drive.
 * Auto-creates the library subfolder if needed.
 */
function savePdfToDrive(config, base64Bytes, filename, libraryName) {
  if (!config.pdfFolderId) { throw new Error('pdfFolderId not provided in config (PDF_FOLDER_ID Script Property)'); }
  const parentFolder = DriveApp.getFolderById(config.pdfFolderId);
  const subName      = (libraryName || 'Default').trim();
  // Find or create library subfolder
  let subFolder;
  const existingIter = parentFolder.getFoldersByName(subName);
  if (existingIter.hasNext()) {
    subFolder = existingIter.next();
  } else {
    subFolder = parentFolder.createFolder(subName);
    Logger.log('BibManCore: created new library subfolder: ' + subName);
  }
  // Build the blob
  const blob = Utilities.newBlob(
    Utilities.base64Decode(base64Bytes),
    'application/pdf',
    filename
  );
  // Overwrite if file with same name already exists
  const existingFiles = subFolder.getFilesByName(filename);
  if (existingFiles.hasNext()) { existingFiles.next().setTrashed(true); }
  const file = subFolder.createFile(blob);
  file.setName(filename);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { ok: true, file_id: file.getId() };
}

/**
 * exportBibText: Returns raw .bib content as a string.
 * Used by GooTeX loopback (no Drive write needed).
 */
function exportBibText(config, library) {
  const resolved = resolveConfig(config);
  const url      = `${resolved.baseUrl}/api/export/bib-text?library=${encodeURIComponent(library || '')}`;
  return UrlFetchApp.fetch(url, {
    method:  'get',
    headers: { 'X-BibMan-Credential': resolved.credential },
    muteHttpExceptions: true,
    deadline: 55,
  }).getContentText();
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 11. BOOKMARKLET ───────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
function getBookmarkletCode(config) {
  const captureUrl    = config.captureUrl    || '';
  const credential = config.credential || '';
  const dashUrl    = config.dashUrl    || '';
  const bmUrl = 'https://raw.githubusercontent.com/pmarcum/BibMan/main/bookmarklet.js?t=' + Date.now();
  try {
    const resp = UrlFetchApp.fetch(bmUrl, { muteHttpExceptions: true, deadline: 10 });
    if (resp.getResponseCode() === 200) {
      const code = resp.getContentText()
        .replace('__GAS_URL__', captureUrl)
        .replace('__CREDENTIAL__', credential)
        .replace('__DASHBOARD_URL__', dashUrl);
      return 'javascript:' + encodeURIComponent(code);
    }
  } catch(err) {
    Logger.log('BibManCore.getBookmarkletCode: GitHub fetch failed: ' + err.message);
  }
  return 'javascript:alert("Bookmarklet unavailable")';
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 12. CRON ──────────────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * runNightlyCron: Called by a time-based trigger in the thin client.
 * GAS triggers can only fire functions in the bound script — the thin client
 * must define `function runNightlyCron() { BibManCore.runNightlyCron(_cfg()); }`
 */
function runNightlyCron(config) {
  const resolved = resolveConfig(config);
  try {
    const resp = UrlFetchApp.fetch(resolved.baseUrl + '/api/cron/run', {
      method:      'post',
      contentType: 'application/json',
      headers: {
        'X-BibMan-Credential': resolved.credential,
        'X-Gemini-Key':        resolved.geminiKey     || '',
        'X-Embed-Model':       resolved.embedModel,
        'X-Generate-Model':    resolved.generateModel,
      },
      payload:            JSON.stringify({}),
      muteHttpExceptions: true,
      deadline:           30,
    });
    Logger.log('BibManCore.runNightlyCron response: ' + resp.getContentText());
  } catch(err) {
    Logger.log('BibManCore.runNightlyCron failed: ' + err.message);
  }
}

/**
 * setupCronTrigger: Creates (or recreates) the daily nightly cron trigger.
 * Must be called once from the thin client's script editor (not from a trigger).
 * The thin client must define `function setupCronTrigger()` that calls this.
 */
function setupCronTrigger() {
  // Delete any existing cron triggers to avoid duplicates
  ScriptApp.getProjectTriggers()
    .filter(t => t.getHandlerFunction() === 'runNightlyCron')
    .forEach(t => ScriptApp.deleteTrigger(t));
  // Daily at 5am Pacific / noon UTC
  ScriptApp.newTrigger('runNightlyCron')
    .timeBased()
    .atHour(5)
    .nearMinute(0)
    .everyDays(1)
    .inTimezone('America/Los_Angeles')
    .create();
  Logger.log('BibManCore.setupCronTrigger: daily trigger created at 5am Pacific');
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 13. API CONVENIENCE WRAPPERS ─────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// Libraries
function getLibraries(config)               { return apiCall(config, 'GET',    '/api/libraries'); }
function getCurrentLibrary(config)          { return apiCall(config, 'GET',    '/api/libraries/current'); }
function switchLibrary(config, name)        { return apiCall(config, 'POST',   '/api/libraries/switch', { library_name: name }); }
function createLibrary(config, name)        { return apiCall(config, 'POST',   '/api/libraries', { name }); }
function deleteLibrary(config, id)          { return apiCall(config, 'DELETE', `/api/libraries/${id}`); }
// Papers
function getPapers(config, library, everyone) {
  const params = {};
  if (library)  params.library  = library;
  if (everyone) params.everyone = '1';
  return apiCall(config, 'GET', '/api/papers', null, Object.keys(params).length ? params : null);
}
function getPaper(config, paperId, everyone) {
  const params = everyone ? { everyone: '1' } : {};
  return apiCall(config, 'GET', `/api/papers/${paperId}`, null, Object.keys(params).length ? params : null);
}
function updatePaper(config, paperId, data)    { return apiCall(config, 'PATCH',  `/api/papers/${paperId}`, data); }
function deletePaper(config, paperId)          { return apiCall(config, 'DELETE', `/api/papers/${paperId}`); }
function updateReadStatus(config, paperId, s)  { return apiCall(config, 'PATCH',  `/api/papers/${paperId}/read-status`, { read_status: s }); }
function updateBibtex(config, paperId, bib)    { return apiCall(config, 'PUT',    `/api/papers/${paperId}/bibtex`, { bibtex: bib }); }
function setPdfSource(config, paperId, u, f)   { return apiCall(config, 'PATCH',  `/api/papers/${paperId}/pdf-source`, { pdf_url: u, file_id: f }); }
function getIngestStatus(config, paperId)      { return apiCall(config, 'GET',    `/api/papers/${paperId}/ingest-status`); }
function rerunIngest(config, paperId)          { return apiCall(config, 'POST',   `/api/papers/${paperId}/rerun-ingest`); }
function bulkReextract(config, all, library)   { return apiCall(config, 'POST',   '/api/papers/bulk-reextract', { all: !!all, library: library || '' }); }
function addPaperManual(config, data) {
  if (data.journal) data.journal = normalizeJournalToMacro(data.journal);
  return apiCall(config, 'POST', '/api/papers/add-manual', data);
}
function importBib(config, bibContent, library) { return apiCall(config, 'POST', '/api/papers/import-bib', { bib_content: bibContent, library: library || '' }); }
// Search
function vennSearch(config, queries, globalExcludes, library) {
  return apiCall(config, 'POST', '/api/search/venn', {
    queries,
    global_excludes: globalExcludes || [],
    library: library || '',
  });
}
function searchSuggestions(config, q) { return apiCall(config, 'GET', '/api/search/suggestions', null, { q }); }
// Annotations
function createAnnotation(config, data)        { return apiCall(config, 'POST',   '/api/annotations', data); }
function updateAnnotation(config, id, data)    { return apiCall(config, 'PATCH',  `/api/annotations/${id}`, data); }
function deleteAnnotation(config, id)          { return apiCall(config, 'DELETE', `/api/annotations/${id}`); }
function updateAnnotationFlags(config, id, f)  { return apiCall(config, 'PATCH',  `/api/annotations/${id}/flags`, f); }
// Synonyms
function getSynonyms(config)              { return apiCall(config, 'GET',    '/api/synonyms'); }
function addSynonym(config, a, b)         { return apiCall(config, 'POST',   '/api/synonyms', { term_a: a, term_b: b }); }
function approveSynonym(config, id)       { return apiCall(config, 'POST',   `/api/synonyms/${id}/approve`); }
function deleteSynonym(config, id)        { return apiCall(config, 'DELETE', `/api/synonyms/${id}`); }
function importDefaultSynonyms(config)    { return apiCall(config, 'POST',   '/api/synonyms/import-defaults'); }
// Annotated papers / config / status
function getAnnotatedPapers(config)       { return apiCall(config, 'GET',   '/api/my-annotated-papers'); }
function getConfig_(config)               { return apiCall(config, 'GET',   '/api/config'); }
function updateConfig(config, data)       { return apiCall(config, 'PATCH', '/api/config', data); }
function getStatus(config)                { return apiCall(config, 'GET',   '/api/status'); }
// Export
function exportBib(config, bibkeys, library) { return apiCall(config, 'POST', '/api/export/bib', { bibkeys, library: library || '' }); }
// Mentions
function createMention(config, data)      { return apiCall(config, 'POST',  '/api/mentions', data); }
function getUnreadMentions(config)        { return apiCall(config, 'GET',   '/api/mentions/unread'); }
function markMentionSeen(config, id)      { return apiCall(config, 'PATCH', `/api/mentions/${id}/seen`); }
function markAllMentionsSeen(config)      { return apiCall(config, 'PATCH', '/api/mentions/seen-all'); }
function getMentionCount(config)          { return apiCall(config, 'GET',   '/api/mentions/count'); }
// Team
function getTeam(config)                  { return apiCall(config, 'GET',    '/api/team'); }
function addTeamMember(config, username)  { return apiCall(config, 'POST',   '/api/team', { username }); }
function removeTeamMember(config, id)     { return apiCall(config, 'DELETE', `/api/team/${id}`); }
// Embeddings
function backfillEmbeddings(config, paperId) { return apiCall(config, 'POST', `/api/papers/${paperId}/backfill-embeddings`); }
function getBackfillList(config, library)    { return apiCall(config, 'GET',  '/api/backfill/list', null, library ? { library } : null); }
// Tags
function getTagLabels(config, everyone)         { return apiCall(config, 'GET',    `/api/tags/labels${everyone ? '?all=1' : ''}`); }
function createTagLabel(config, label, color)   { return apiCall(config, 'POST',   '/api/tags/labels', { label, color }); }
function updateTagLabel(config, id, label, color){ return apiCall(config, 'PATCH', `/api/tags/labels/${id}`, { label, color }); }
function deleteTagLabel(config, id)             { return apiCall(config, 'DELETE', `/api/tags/labels/${id}`); }
function getPaperTags(config, paperId, everyone){ return apiCall(config, 'GET',    `/api/papers/${paperId}/tags${everyone ? '?all=1' : ''}`); }
function addPaperTag(config, paperId, labelId, annotationId) {
  return apiCall(config, 'POST', `/api/papers/${paperId}/tags`, {
    label_id: labelId,
    annotation_id: annotationId || null,
  });
}
function removePaperTag(config, paperId, labelId, annotationId) {
  const qs = annotationId ? `?annotation_id=${annotationId}` : '';
  return apiCall(config, 'DELETE', `/api/papers/${paperId}/tags/${labelId}${qs}`);
}
function getTaggedPapers(config, labelIds, everyone) {
  const params = labelIds.map(id => `label_id=${id}`).join('&') + (everyone ? '&all=1' : '');
  return apiCall(config, 'GET', `/api/papers/tagged?${params}`);
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── 14. BOOKMARKLET METADATA-CAPTURE HANDLER ─────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════
// These functions are called by the BibMan_Bookmarklet_Capture_WebApp thin client.
// That webapp executes as Me (the deployer) — correct, since bookmarklet POSTs
// have no visiting Google user identity. The visitor's username comes from
// localStorage set during their dashboard session, passed as data._username.
//
// The bookmarklet fires TWO parallel fetches on open:
//   1. extract_and_preview — paper metadata (slow: ADS or Gemini)
//   2. get_libraries       — library list + current (fast: Flask)
// These are intentionally separate so library dropdown populates quickly
// while metadata is still loading. Do NOT bundle libraries into
// extract_and_preview — that would serialize two calls into one slower one.
//
// Append this section to the bottom of BibMan_Core.gs.
// ═══════════════════════════════════════════════════════════════════════════════
/**
 * captureDoPost: Full handler for BibMan_Bookmarklet_Capture_WebApp doPost().
 * Routes by action:
 *   get_libraries       — returns library list + current (no credential required)
 *   extract_and_preview — ADS lookup or Gemini extraction for a URL/identifier
 *   save_captured       — saves a paper to the backend (credential required)
 */
function captureDoPost(config, e) {
  // Build inner response as a plain object first, then inject update flag,
  // then wrap in ContentService at the very end. This lets us add
  // bibman_bookmarklet_capture_update_available to every response path without repeating ourselves.
  function _buildResponseObj() {
    try {
      const data       = JSON.parse(e.postData.contents);
      const credential = config.credential || '';
      // ── get_libraries: no credential required ────────────────────────────
      if (data.action === 'get_libraries') {
        try {
          const full = _captureGetLibrariesFull(config);
          return { libraries: full.libraries || [], current: full.current || '' };
        } catch(err) {
          return { libraries: [], current: '', error: err.message };
        }
      }
      // ── All other actions require credential ──────────────────────────────
      if (data.credential !== credential) { return { error: 'unauthorized' }; }
      // ── extract_and_preview ───────────────────────────────────────────────
      if (data.action === 'extract_and_preview') {
        const identifier = (data.identifier || '').trim();
        // Fast path: identifier → ADS lookup
        if (identifier) {
          try {
            const paper = lookupPaperByIdentifier(config, identifier);
            if (paper && paper.title) {
              paper.source = 'ads';
              return paper;
            }
          } catch(err) { /* fall through */ }
        }
        // Slow path: Gemini extract via VM
        try {
          const resolved = resolveConfig(config);
          const resp = UrlFetchApp.fetch(
            resolved.baseUrl + '/api/papers/extract-metadata',
            {
              method:      'post',
              contentType: 'application/json',
              headers: {
                'X-BibMan-Credential': resolved.credential,
                'X-Gemini-Key':        resolved.geminiKey || '',
              },
              payload:            JSON.stringify({ url: data.url }),
              muteHttpExceptions: true,
              deadline:           55,
            }
          );
          const meta   = JSON.parse(resp.getContentText());
          const ident2 = (meta.doi || meta.arxiv_id || '').trim();
          if (ident2 && !meta.error) {
            try {
              const adsPaper = lookupPaperByIdentifier(config, ident2);
              if (adsPaper && adsPaper.title) {
                adsPaper.source    = 'ads_via_gemini';
                return adsPaper;
              }
            } catch(err) {}
          }
          return meta;
        } catch(err) {
          return { error: err.message };
        }
      }
      // ── save_captured ─────────────────────────────────────────────────────
      if (data.action === 'save_captured') {
        try {
          const result = addPaperManual(config, {
            bibkey:      (data.bibkey   || '').trim(),
            title:       (data.title    || '').trim(),
            authors:     (data.authors  || '').trim(),
            year:        String(data.year || '').trim(),
            journal:     normalizeJournalToMacro(data.journal || ''),
            volume:      (data.volume   || '').trim(),
            pages:       (data.pages    || '').trim(),
            doi:         (data.doi      || '').trim(),
            arxiv_id:    (data.arxiv_id || '').trim(),
            bibcode:     (data.bibcode  || '').trim(),
            identifiers: data.identifiers || [],
            pdf_url:     (!data.doi && !data.arxiv_id) ? (data.url || '') : '',
            library:     (data.library  || '').trim(),
            _username:   (data._username|| '').trim(),
          });
          if (result && result.duplicate) {
            result.error = `Already in library as ${result.bibkey}`;
          }
          return result;
        } catch(err) {
          return { error: err.message };
        }
      }
      return { error: 'unknown action' };
    } catch(err) {
      return { error: err.message };
    }
  }
  // Build response, inject capture update flag if needed, return as JSON
  const responseObj = _buildResponseObj();
  try {
    const updates = _checkForUpdates(
      config.frontendThinClientVersion || 1,
      config.bookmarkletCaptureVersion || 1,
      config.linkedCoreVersion         || BIBMAN_CORE_LIBRARY_VERSION
    );
    if (updates.bookmarkletCaptureUpdateAvailable) {
      responseObj.bibman_bookmarklet_capture_update_available = true;
      responseObj.bibman_bookmarklet_capture_webapp_notes = updates.bookmarkletCaptureNotes || '';
    }
  } catch(err) {
    Logger.log('_checkForUpdates error: ' + err.message);
  }
  return ContentService.createTextOutput(JSON.stringify(responseObj))
    .setMimeType(ContentService.MimeType.JSON);
}

/**
 * getBookmarkletCodeCapture: Bookmarklet code for the meta-data capture webapp.
 * config.captureUrl must be set to ScriptApp.getService().getUrl() by the
 * bookmarklet capture thin client — that's the __GAS_URL__ the bookmarklet POSTs to.
 * config.dashUrl is the dashboard webapp URL for the __DASHBOARD_URL__ placeholder.
 */
function getBookmarkletCodeCapture(config) { return getBookmarkletCode(config); }

/**
 * _captureGetLibrariesFull: Internal helper — fetches /api/libraries/full from VM.
 * Returns { libraries: [], current: '' } on any failure.
 */
function _captureGetLibrariesFull(config) {
  try {
    return apiCall(config, 'GET', '/api/libraries/full');
  } catch(err) {
    Logger.log('BibManCore._captureGetLibrariesFull error: ' + err.message);
    return { libraries: [], current: '' };
  }
}
