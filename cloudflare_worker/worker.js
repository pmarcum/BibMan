/**
 * BibMan PDF proxy (Cloudflare Worker)
 * The dashboard loads arXiv PDFs as  CF_WORKER_URL?url=<encoded arXiv PDF URL>.  arXiv doesn't send the CORS
 * headers a browser needs for PDF.js to read the file, so this Worker fetches it and adds them.
 * Only arXiv addresses are proxied, so the Worker can't be used as a general-purpose proxy by strangers.
 * Deploy: Cloudflare dashboard → Workers & Pages → Create → Worker → paste this file → Deploy.
 */
const ALLOWED_HOSTS = ['arxiv.org', 'www.arxiv.org', 'export.arxiv.org'];

export default {
  async fetch(request) {
    const raw = new URL(request.url).searchParams.get('url');
    if (!raw) return new Response('url param required', { status: 400 });
    let target;
    try { target = new URL(raw); } catch { return new Response('invalid url', { status: 400 }); }
    if (!['https:', 'http:'].includes(target.protocol) || !ALLOWED_HOSTS.includes(target.hostname))
      return new Response('only arXiv PDFs are proxied', { status: 403 });
    target.protocol = 'https:';  // older library entries may store http:// links
    const r = await fetch(target.toString(), { headers: { 'User-Agent': 'BibMan/2.0' } });
    if (!r.ok) return new Response(`upstream returned ${r.status}`, { status: 502, headers: { 'Access-Control-Allow-Origin': '*' } });
    return new Response(r.body, { headers: { 'Content-Type': 'application/pdf', 'Access-Control-Allow-Origin': '*' } });
  },
};
