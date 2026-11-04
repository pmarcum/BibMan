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
 *   accessCode:     string   // BIBMAN_ACCESS_CODE: the dashboard's access code (Core 9; replaces the access sheet)
 *   adminEmails:    string   // ADMIN_EMAILS: who sees the Admin menu, emails separated by commas (Core 9)
 *   coreMembers:    string   // CORE_MEMBERS: people who never need the access code, emails separated by commas
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
 *       accessCode:    p.getProperty('BIBMAN_ACCESS_CODE')  || '',
 *       adminEmails:   p.getProperty('ADMIN_EMAILS')        || '',
 *       coreMembers:   p.getProperty('CORE_MEMBERS')        || '',
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
// THE CORE VERSION NUMBER IS SET HERE, IN THE CODE (since Core 8). Before Deploy → Manage deployments → New version,
// set it to the number that deployment will get, and use the same number in version.json.
// Why not a Script Property: properties are not saved with a library version, so every web app would report the
// newest number even while still running an older Core, and the "update Core" banner would never appear.
// The old Script Property BIBMAN_CORE_LIBRARY_VERSION is no longer read and can be deleted.
const BIBMAN_CORE_LIBRARY_VERSION = 10;
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
      bookmarkletCaptureNotes: v.bibman_bookmarklet_capture_webapp_notes       || '',
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
 * needs: credential, current user info, admin flag (not the VM address or the Gemini key, since Core 4).
 * Has version check so Index.html can show update banners
 */
function getClientConfig(config) {
  const resolved = resolveConfig(config);
  const email    = Session.getActiveUser().getEmail();
  const updates  = _checkForUpdates(
    config.frontendThinClientVersion  || 1,
    config.bookmarkletCaptureVersion  || 1,
    config.linkedCoreVersion          || BIBMAN_CORE_LIBRARY_VERSION
  );
  return {
    // baseUrl (the VM address) is no longer sent to the browser (Core 4): the dashboard never connects to the VM directly.
    credential:                        resolved.credential,
    // geminiKey is no longer sent to the browser (Core 4): Venn Search runs server-side through vennSearch().
    currentUser:                       email ? email.split('@')[0] : '',
    currentUserEmail:                  email || '',
    isAdmin:                           _isAdmin_(config, email),
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
/**
 * _requireAccess_: every dashboard call must come from someone signed in to Google who has entered the current
 * access code. doGet checks when the page loads, but the functions behind the page are callable directly by anyone
 * who can open the web app, so dispatch() checks again, on every call: changing the code takes effect at once.
 */
function _requireAccess_(config) {
  const email = (Session.getActiveUser().getEmail() || '').trim();
  if (!email) throw new Error('BibMan: you are not signed in to a Google account.');
  if (_isCoreMember_(config, email)) return;
  if (!_accessCode_(config)) throw new Error('BibMan: no access code has been set up yet (Script Property BIBMAN_ACCESS_CODE).');
  if (!_hasAccess_(config)) throw new Error('BibMan: the access code has changed, or has not been entered. Reload BibMan to enter it.');
}

function dispatch(config, fn, ...args) {
  // The one call allowed before the access code is entered: checking a typed code (from the access-code page)
  if (fn === 'enterAccessCode') {
    if (!(Session.getActiveUser().getEmail() || '').trim()) throw new Error('BibMan: you are not signed in to a Google account.');
    return { ok: _rememberAccessCode_(config, args[0]) };
  }
  _requireAccess_(config);
  const table = {
    // Config / user
    getClientConfig:       () => getClientConfig(config),
    getCfWorkerUrl:        () => getCfWorkerUrl(config),
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
    vennSearchResult:      (jobId) => vennSearchResult(config, jobId),
    vennSearchCancel:      (jobId) => vennSearchCancel(config, jobId),
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
    createTagLabel:        (label, color, isPrivate) => createTagLabel(config, label, color, isPrivate),
    setTagLabelPrivate:    (id, isPrivate) => setTagLabelPrivate(config, id, isPrivate),
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
  const gate = dashboardGate(config, (e && e.parameter) || {});
  if (gate) return HtmlService.createHtmlOutput(gate).setTitle('BibMan — access code')
                     .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
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
      // Where the server sends PDFs to be saved in Drive (Core 10): the bookmarklet's web app, which runs as the owner
      // and needs no Google sign-in. The dashboard's web app runs as the person using it and refuses the server (401).
      'X-GAS-Webapp-URL':    config.captureUrl || config.dashUrl || ScriptApp.getService().getUrl(),
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
// Since Core 9 (2 Nov 2026) the dashboard is open to anyone signed in to Google who has the link AND has entered
// the access code, set in the Frontend project's Script Property BIBMAN_ACCESS_CODE (no access sheet any more).
// The code is entered once per person (in the link as ?access=CODE, or in the box BibMan shows) and remembered for
// that person, as a fingerprint (SHA-256), never as the code itself, until the code is changed; then everyone is
// asked once for the new one. Capitals count; spaces at either end are ignored. With no code set, nobody gets in.
// Admins (who see the Admin menu) are listed in the Script Property ADMIN_EMAILS. Core members, listed in CORE_MEMBERS,
// and admins never need the code: they are let in by their Google email (checked on every call, so removing someone
// from the list takes effect at once). Emails are compared ignoring capitals; separate them with commas.
// The bookmarklet and gooTeX don't use the code: the bookmarklet carries GAS_CREDENTIAL, gooTeX its own
// read-only EXPORT_CREDENTIAL (see MAINTENANCE.md, "Adding and removing people").
function _accessCode_(config) { return (config.accessCode || '').trim(); }
function _sha256_(text) {
  return Utilities.base64Encode(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text, Utilities.Charset.UTF_8));
}
// One remembered entry per person and dashboard: groups that share this library never share an answer.
function _accessKey_(config) { return 'bm_access_' + _sha256_(config.dashUrl || 'dashboard').replace(/[^A-Za-z0-9]/g, '').slice(0, 16); }
function _accessMark_(config) { return _sha256_('bibman-access\n' + (config.dashUrl || '') + '\n' + _accessCode_(config)); }
function _hasAccess_(config) {
  if (!_accessCode_(config)) return false;
  let saved = '';
  try { saved = PropertiesService.getUserProperties().getProperty(_accessKey_(config)) || ''; } catch (e) { saved = ''; }
  return saved === _accessMark_(config);
}
function _rememberAccessCode_(config, typed) {
  const code = _accessCode_(config);
  if (!code || String(typed == null ? '' : typed).trim() !== code) return false;
  PropertiesService.getUserProperties().setProperty(_accessKey_(config), _accessMark_(config));
  return true;
}
function _inList_(list, email) {
  const me = (email || '').trim().toLowerCase();
  return !!me && (list || '').toLowerCase().split(/[\s,;]+/).filter(Boolean).includes(me);
}
function _isAdmin_(config, email) { return _inList_(config.adminEmails, email); }
// Core members (CORE_MEMBERS) and admins (ADMIN_EMAILS) never need the access code; everyone else does.
function _isCoreMember_(config, email) { return _inList_(config.coreMembers, email) || _isAdmin_(config, email); }

/**
 * dashboardGate: called by the thin client's doGet. Returns '' when this person may open the dashboard, otherwise
 * the HTML of the page to show instead (the access-code box, or why BibMan can't be opened). A correct ?access=CODE
 * in the link is remembered here and lets them straight in.
 */
function dashboardGate(config, params) {
  params = params || {};
  const email = (Session.getActiveUser().getEmail() || '').trim();
  if (!email) return _gatePage_(config, params, 'Please sign in to your Google account, then open this link again.', false);
  if (_isCoreMember_(config, email)) return '';
  if (!_accessCode_(config)) {
    return _gatePage_(config, params, 'BibMan has no access code set up yet. (For the administrator: set the Script ' +
                      'Property BIBMAN_ACCESS_CODE in the BibMan Frontend project.)', false);
  }
  if (params.access != null && String(params.access).trim() !== '') {
    if (_rememberAccessCode_(config, params.access)) return '';
    return _gatePage_(config, params, 'The access code in this link is not (or no longer) the right one. Please type the current code:', true);
  }
  if (_hasAccess_(config)) return '';
  return _gatePage_(config, params, 'Please type the BibMan access code you were given:', true);
}

function _gatePage_(config, params, message, withBox) {
  const esc = t => String(t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const branch = dashboardBranchName(params.branch || '');
  const target = (config.dashUrl || '') + (branch !== 'main' ? '?branch=' + encodeURIComponent(branch) : '');
  const box = !withBox ? '' :
    '<div style="margin-top:16px"><input id="c" type="password" autocomplete="off" autofocus ' +
    'style="font-family:monospace;font-size:14px;padding:7px 10px;width:240px;border-radius:4px;border:1px solid #353540;' +
    'background:#0f0f11;color:#e8e8f0" onkeydown="if(event.key===\'Enter\')go()"> ' +
    '<button onclick="go()" style="font-family:monospace;font-size:13px;padding:7px 14px;border-radius:4px;border:0;' +
    'background:#7eb8f7;color:#0f0f11;font-weight:600;cursor:pointer">Open BibMan</button></div>' +
    '<p id="m" style="color:#888;min-height:1.4em;margin-top:12px"></p>' +
    '<script>const T=' + JSON.stringify(target) + ';' +
    'function m(h){document.getElementById("m").innerHTML=h}' +
    'function go(){const v=document.getElementById("c").value;if(!v.trim())return;m("Checking…");' +
    'google.script.run.withSuccessHandler(function(r){if(r&&r.ok){' +
    'm(\'Code accepted. <a href="\'+T+\'" target="_top" style="color:#7eb8f7">Open BibMan</a>\');' +
    'try{window.open(T,"_top")}catch(e){}}' +
    'else{m("That code didn\'t work. Please check it with whoever gave you the BibMan link.")}})' +
    '.withFailureHandler(function(e){m(String(e&&e.message||e))}).gas("enterAccessCode",v)}</script>';
  return '<html><body style="font-family:monospace;background:#17171a;color:#e8e8f0;margin:0;padding:40px">' +
    '<h2 style="color:#7eb8f7;margin:0 0 12px">BibMan</h2><p style="line-height:1.6;max-width:560px">' + esc(message) + '</p>' +
    box + '</body></html>';
}

// Kept for thin clients from before Core 9, whose doGet still asks for the access sheet's list: an empty list
// lets nobody in, so selecting Core 9 without also updating the Frontend Code.gs fails safe (see version.json).
function getAllowedUsers(config) { return []; }

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
/**
 * dashboardBranchName: the repo branch whose Index.html the dashboard should load. A ?branch=NAME link
 * loads a test page from that branch (Core 6, agreed 29 Oct 2026); anything that isn't a plain branch name
 * (letters, digits, - _ .) means the normal page from main.
 */
function dashboardBranchName(branch) {
  return (typeof branch === 'string' && /^[A-Za-z0-9._-]{1,100}$/.test(branch)) ? branch : 'main';
}
function fetchDashboardHtml(branch) {
  const b = dashboardBranchName(branch);
  const url = 'https://raw.githubusercontent.com/pmarcum/BibMan/' + encodeURIComponent(b) + '/Index.html?t=' + Date.now();
  try {
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true, deadline: 10 });
    if (resp.getResponseCode() === 200) return resp.getContentText();
  } catch(err) {
    Logger.log('BibManCore.fetchDashboardHtml: ' + err.message);
  }
  // A test page that can't be found never falls back to main, so it can't be mistaken for the test page.
  const which = b === 'main' ? '' : ' test page from branch "' + b + '"';
  return '<html><body style="font-family:monospace;padding:2em;">' +
    '<h3 style="color:#f77e7e">BibMan dashboard' + which + ' temporarily unavailable</h3>' +
    '<p>Could not fetch the dashboard' + which + ' from GitHub. ' +
    (b === 'main' ? 'Please try again in a moment.' : 'Check that the branch exists and contains Index.html.') + '</p>' +
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

function getAccessDeniedHtml(email) {   // used by thin clients from before Core 9
  return '<h3 style="font-family:monospace;color:#f77e7e">BibMan has been updated.</h3>' +
    '<p style="font-family:monospace">Its Frontend Code.gs needs the version that goes with Core 9 (see version.json) ' +
    'before anyone can open it.</p>';
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
 * findPdfInDrive: the Drive file ID of BibMan_PDFs/<library>/<filename> (not in Trash), or '' if there is none.
 * Used by the re-save script so a PDF already in Drive is linked rather than saved a second time (Core 10).
 */
function findPdfInDrive(config, filename, libraryName) {
  if (!config.pdfFolderId) { throw new Error('pdfFolderId not provided in config (PDF_FOLDER_ID Script Property)'); }
  const sub = DriveApp.getFolderById(config.pdfFolderId).getFoldersByName((libraryName || 'Default').trim());
  if (!sub.hasNext()) return { ok: true, file_id: '' };
  const files = sub.next().getFilesByName(filename);
  while (files.hasNext()) { const f = files.next(); if (!f.isTrashed()) return { ok: true, file_id: f.getId() }; }
  return { ok: true, file_id: '' };
}

/**
 * resaveMissingPdfs: papers whose PDF never reached Drive (Core 10). With start=false it shows what a re-save would do
 * and how a running one is getting on (nothing changes); with start=true the server starts it in the background.
 * Run from the bookmarklet project's editor (resavePdfsCheck / resavePdfsStart); results in the Execution log.
 */
function resaveMissingPdfs(config, start) {
  const r = apiCall(config, start ? 'POST' : 'GET', '/api/admin/resave-pdfs');
  let text;
  if (!start) {
    const lib = Object.keys(r.by_library || {}).map(function(k) { return '  ' + k + ': ' + r.by_library[k]; }).join('\n');
    const job = r.job || {};
    text = 'Papers with a PDF but no Drive copy: ' + r.candidates + (lib ? '\n' + lib : '') +
           '\nA re-save takes one paper every ' + r.pause_seconds + ' s (about ' + Math.round(r.candidates * r.pause_seconds / 60) +
           ' minutes); PDFs over ' + r.max_mb + ' MB are skipped and listed.' +
           (job.running ? '\nA re-save started ' + job.started + ' UTC is running: ' + job.done + ' of ' + job.total + ' done.' : '') +
           ((r.papers || []).length ? '\nFirst ' + r.papers.length + ':\n  ' + r.papers.join('\n  ') : '');
  } else {
    text = r.started ? 'Re-save started: ' + r.papers + ' papers, about ' + r.minutes + ' minutes. Run resavePdfsCheck to see progress; ' +
                       'the report is written next to the database when it finishes.' : (r.message || r.error || JSON.stringify(r));
  }
  Logger.log(text); console.log(text);
  return r;
}

/**
 * checkPdfLinks: the one-time "viewable by link" check of BibMan_PDFs and all its subfolders (Core 10).
 * Run from the bookmarklet project's editor (checkPdfLinks / fixPdfLinks). With apply=false it only lists the PDFs
 * that are not viewable by anyone with the link; with apply=true it switches them to "anyone with the link can view".
 * Files it may not change (e.g. owned by someone else) are listed instead. It stops itself after about 5 minutes
 * (Apps Script allows 6) and says so; running it again carries on where it stopped.
 */
function checkPdfLinks(config, apply) {
  if (!config.pdfFolderId) { throw new Error('PDF_FOLDER_ID is not set in this project\'s Script Properties'); }
  const t0 = Date.now(), BUDGET = 5 * 60 * 1000;
  const token = ScriptApp.getOAuthToken();
  const list = function(q) {
    let out = [], page = '';
    do {
      const url = 'https://www.googleapis.com/drive/v3/files?pageSize=1000&supportsAllDrives=true&includeItemsFromAllDrives=true' +
                  '&fields=' + encodeURIComponent('nextPageToken,files(id,name,owners(emailAddress))') +
                  '&q=' + encodeURIComponent(q) + (page ? '&pageToken=' + encodeURIComponent(page) : '');
      const r = UrlFetchApp.fetch(url, { headers: { Authorization: 'Bearer ' + token }, muteHttpExceptions: true });
      if (r.getResponseCode() !== 200) throw new Error('Drive search failed: HTTP ' + r.getResponseCode() + ' ' + r.getContentText().slice(0, 200));
      const j = JSON.parse(r.getContentText()); out = out.concat(j.files || []); page = j.nextPageToken || '';
    } while (page);
    return out;
  };
  // every folder under BibMan_PDFs, then the PDFs in each that are not viewable by link
  const folders = [{ id: config.pdfFolderId, path: 'BibMan_PDFs' }];
  for (let i = 0; i < folders.length; i++) {
    list("'" + folders[i].id + "' in parents and trashed=false and mimeType='application/vnd.google-apps.folder'")
      .forEach(function(f) { folders.push({ id: f.id, path: folders[i].path + '/' + f.name }); });
  }
  const priv = [];
  folders.forEach(function(fo) {
    list("'" + fo.id + "' in parents and trashed=false and mimeType='application/pdf' and visibility='limited'")
      .forEach(function(f) { priv.push({ id: f.id, name: f.name, path: fo.path, owner: ((f.owners || [])[0] || {}).emailAddress || '?' }); });
  });
  const lines = ['BibMan_PDFs: ' + folders.length + ' folders checked; ' + priv.length + ' PDF(s) not viewable by link' +
                 (apply ? '' : ' (nothing changed: run fixPdfLinks to switch them)')];
  let changed = 0; const failed = [], notDone = [];
  priv.forEach(function(f) {
    if (!apply) { lines.push('  ' + f.path + '/' + f.name + '   (owner ' + f.owner + ')'); return; }
    if (Date.now() - t0 > BUDGET) { notDone.push(f); return; }
    try { DriveApp.getFileById(f.id).setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); changed++; }
    catch (e) { failed.push(f.path + '/' + f.name + '   (owner ' + f.owner + '): ' + e.message); }
  });
  if (apply) {
    lines.push('switched to "anyone with the link can view": ' + changed);
    if (failed.length) { lines.push('could not be changed (' + failed.length + '):'); failed.forEach(function(x) { lines.push('  ' + x); }); }
    if (notDone.length) lines.push('stopped after 5 minutes with ' + notDone.length + ' still to do: run fixPdfLinks again to carry on');
  }
  const text = lines.join('\n'); Logger.log(text); console.log(text);
  return { folders: folders.length, not_viewable: priv.length, changed: changed, failed: failed.length, remaining: notDone.length };
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
/**
 * vennSearch: Venn Search, sent server-to-server from Apps Script, so the browser never connects to the VM
 * directly (networks that block the VM's domain still work) and the Gemini key stays in Apps Script.
 *
 * Since Core 4 the dashboard passes an options object. A large search can take longer than the ~1 minute
 * Apps Script allows per request, so the server runs it as a background job: this call starts it and waits
 * up to VENN_FIRST_WAIT_MS for the result (enough for most searches). If it isn't ready, it returns
 * { pending: true, job_id }, and the dashboard calls vennSearchResult(job_id), which waits up to
 * VENN_WAIT_MS each time, until it is; vennSearchCancel(job_id) stops it. The server stops a search
 * after VENN_JOB_MAX_SECONDS (its setting, 2 minutes) and passes that limit on as max_seconds, so the
 * dashboard's wording follows it. The older (queries, globalExcludes, library) form still runs as a single request.
 */
const VENN_FIRST_WAIT_MS = 5000, VENN_WAIT_MS = 40000, VENN_POLL_MS = 1500;
function vennSearch(config, queriesOrOpts, globalExcludes, library) {
  if (Array.isArray(queriesOrOpts)) {
    return apiCall(config, 'POST', '/api/search/venn', {
      queries: queriesOrOpts, global_excludes: globalExcludes || [], library: library || '',
    });
  }
  const o = queriesOrOpts || {};
  const body = { queries: o.queries || [], global_excludes: o.global_excludes || [], library: o.library || '' };
  ['use_synonyms', 'use_semantic', 'max_results', 'everyone', 'current_user']
    .forEach(k => { if (o[k] !== undefined) body[k] = o[k]; });
  const started = apiCall(config, 'POST', '/api/search/venn/start', body);
  if (!started || !started.job_id) throw new Error('The server did not start the search.');
  return vennSearchResult(config, started.job_id, VENN_FIRST_WAIT_MS);
}
function vennSearchResult(config, jobId, waitMs) {
  const until = Date.now() + (waitMs || VENN_WAIT_MS);
  while (true) {
    const r = apiCall(config, 'GET', '/api/search/venn/result/' + encodeURIComponent(jobId));
    if (r.status === 'done')  return r.result;
    if (r.status === 'error') throw new Error(r.error || 'The search failed.');
    if (Date.now() + VENN_POLL_MS > until) return { pending: true, job_id: jobId, max_seconds: r.max_seconds };
    Utilities.sleep(VENN_POLL_MS);
  }
}
function vennSearchCancel(config, jobId) {
  return apiCall(config, 'POST', '/api/search/venn/cancel/' + encodeURIComponent(jobId));
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
function createTagLabel(config, label, color, isPrivate) { return apiCall(config, 'POST', '/api/tags/labels', { label, color, is_private: !!isPrivate }); }
function setTagLabelPrivate(config, id, isPrivate) { return apiCall(config, 'PATCH', `/api/tags/labels/${id}`, { is_private: !!isPrivate }); }
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
      // ── upload_pdf: the server hands over a PDF to save in BibMan_PDFs/<library>/ (Core 10) ──
      if (data.action === 'upload_pdf') {
        try { return savePdfToDrive(config, data.pdf_base64, data.filename, data.library_name || ''); }
        catch(err) { return { ok: false, error: err.message }; }
      }
      // ── find_pdf: is a PDF of this name already in BibMan_PDFs/<library>/? (used when re-saving) ──
      if (data.action === 'find_pdf') {
        try { return findPdfInDrive(config, data.filename, data.library_name || ''); }
        catch(err) { return { ok: false, error: err.message }; }
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
