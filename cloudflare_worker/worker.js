/**
 * BibMan PDF proxy (Cloudflare Worker)
 * Fetches a PDF from any website and adds the headers a browser needs to display it (arXiv and many publishers
 * don't send them). Called as   https://<worker>.workers.dev/<PROXY_KEY>?url=<encoded PDF URL>
 *
 * Protection against strangers using it:
 *   1. The secret PROXY_KEY must be the first part of the path. Set it under Settings → Variables and Secrets
 *      (type: Secret). Put the same key at the end of CF_WORKER_URL in the frontend's Script Properties:
 *      CF_WORKER_URL = https://<worker>.workers.dev/<PROXY_KEY>
 *   2. Only real PDF files are passed on (the file must start with "%PDF"), up to MAX_BYTES, so the Worker can't
 *      be used as a general web proxy even by someone who has the key.
 */
const MAX_BYTES = 60 * 1024 * 1024;  // 60 MB; Workers have ~128 MB of memory
const CORS = { 'Access-Control-Allow-Origin': '*' };
const fail = (msg, status) => new Response(msg, { status, headers: CORS });

export default {
  async fetch(request, env) {
    if (!env.PROXY_KEY) return fail('PROXY_KEY secret is not set on this Worker', 500);
    const { pathname, searchParams } = new URL(request.url);
    if (pathname.slice(1) !== env.PROXY_KEY) return fail('forbidden', 403);
    const raw = searchParams.get('url');
    if (!raw) return fail('url param required', 400);
    let target;
    try { target = new URL(raw); } catch { return fail('invalid url', 400); }
    if (!['https:', 'http:'].includes(target.protocol)) return fail('only http(s) links', 400);

    const r = await fetch(target.toString(), { headers: { 'User-Agent': 'BibMan/2.0' }, redirect: 'follow' });
    if (!r.ok) return fail(`upstream returned ${r.status}`, 502);
    if (Number(r.headers.get('content-length') || 0) > MAX_BYTES) return fail('file too large', 413);
    const buf = await r.arrayBuffer();
    if (buf.byteLength > MAX_BYTES) return fail('file too large', 413);
    const head = new TextDecoder().decode(new Uint8Array(buf, 0, Math.min(1024, buf.byteLength)));
    if (!head.includes('%PDF')) return fail('not a PDF', 415);
    return new Response(buf, { headers: { 'Content-Type': 'application/pdf', ...CORS } });
  },
};
