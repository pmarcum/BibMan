#!/usr/bin/env python3
"""
Repair author lists and titles whose accents were damaged (12 Nov 2026).

The move from the old spreadsheet into BibMan (March–April 2026) read the old BibTeX with bibtexparser's "convert to
Unicode", which mangles LaTeX accents: {\'\i} became a dotless ı plus a loose accent mark, some letters were lost or
moved, stray backslashes were left before accented letters. This script finds those papers and puts back the author
list (and the title, where it is damaged too) from NASA ADS, as plain UTF-8, which is how BibMan stores names.

  1. report: looks only (the database is opened read-only). Asks ADS for each damaged paper (by bibcode, else DOI)
     and writes report.html (before and after, for you to read) and plan.json (for step 2) into --out.
       ADS_TOKEN=... python bibman_repair_accents.py report --out /tmp/accent_repair
  2. apply: writes the plan's changes, except papers named in --skip; papers listed under "only a dotless i" (which
     can be a correct Turkish name such as Yıldız) are changed only when named in --include. A paper whose authors or
     title changed since the report is left alone. Before writing, it saves the old values to undo-<time>.json.
       python bibman_repair_accents.py apply --plan /tmp/accent_repair/plan.json [--skip key1,key2] [--include key3]
  3. undo, if ever needed: puts back exactly the values saved in an undo file.
       python bibman_repair_accents.py undo --undo /tmp/accent_repair/undo-<time>.json

Author lists keep the first 10 names and then "et al." (as the damaged entries had); titles are replaced only when
they are damaged themselves. Run as the bibman user, with BibMan's own Python (it needs only requests).
"""
import argparse, html, json, os, re, sqlite3, sys, time, unicodedata
from datetime import datetime, timezone

DB_PATH        = os.environ.get('DB_PATH', '/home/bibman/bibman.db')
ADS_URL        = 'https://api.adsabs.harvard.edu/v1/search/query'
MAX_AUTHORS    = 10
DAMAGE         = re.compile('[̀-ͯ´¨˜ˆˇ˘˙˚˛]|\\\\[^\\x00-\\x7f]')
DOTLESS_I      = re.compile('ı')
_DOTLESS_ACC   = re.compile('ı([̀-ͯ])')

def clean_text(s):
    """Plain, composed UTF-8 (as the server's clean_text)."""
    return unicodedata.normalize('NFC', _DOTLESS_ACC.sub(lambda m: 'i' + m.group(1), s or ''))

def classify(text):
    if DAMAGE.search(text or ''):    return 'damaged'
    if DOTLESS_I.search(text or ''): return 'check'
    return None

def ads_lookup(session, token, bibcode, doi):
    """ADS's record for a paper, by bibcode, else by DOI: {bibcode, author, title} or None."""
    for q in ([f'bibcode:"{bibcode}"'] if bibcode else []) + ([f'doi:"{doi}"'] if doi else []):
        for attempt in range(3):
            r = session.get(ADS_URL, params={'q': q, 'fl': 'bibcode,author,title', 'rows': 1},
                            headers={'Authorization': f'Bearer {token}'}, timeout=20)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1)); continue
            r.raise_for_status()
            docs = r.json().get('response', {}).get('docs', [])
            if docs:
                return docs[0]
            break
        time.sleep(0.2)
    return None

def ads_authors(names):
    names = [clean_text(n).strip() for n in names or [] if n and n.strip()]
    text = ' and '.join(names[:MAX_AUTHORS])
    return text + (' and et al.' if len(names) > MAX_AUTHORS else '')

def report(args):
    token = os.environ.get('ADS_TOKEN', '').strip()
    if not token:
        sys.exit('Set ADS_TOKEN first (your NASA ADS API token).')
    import requests
    os.makedirs(args.out, exist_ok=True)
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True); conn.row_factory = sqlite3.Row
    rows = conn.execute('''SELECT p.id, p.bibkey, p.bibcode, p.doi, p.authors, p.title, l.name AS library
                             FROM papers p LEFT JOIN libraries l ON l.id = p.library_id ORDER BY p.bibkey''').fetchall()
    conn.close()
    plan, session = [], requests.Session()
    found = [(r, classify(r['authors']), classify(r['title'])) for r in rows]
    found = [(r, a, t) for r, a, t in found if a or t]
    print(f'{len(found)} papers to look up on ADS ...')
    for n, (r, a_cls, t_cls) in enumerate(found, 1):
        category = 'damaged' if 'damaged' in (a_cls, t_cls) else 'check'
        item = {'id': r['id'], 'bibkey': r['bibkey'], 'library': r['library'], 'category': category,
                'bibcode': r['bibcode'] or '', 'doi': r['doi'] or '',
                'authors_before': r['authors'] or '', 'title_before': r['title'] or '',
                'authors_after': None, 'title_after': None, 'notes': []}
        try:
            doc = ads_lookup(session, token, r['bibcode'], r['doi'])
        except Exception as e:
            doc = None; item['notes'].append(f'ADS could not be asked: {e}')
        if not doc:
            item['notes'].append('not found on ADS: left unchanged')
        else:
            if a_cls:
                item['authors_after'] = ads_authors(doc.get('author'))
            if t_cls and doc.get('title'):
                item['title_after'] = clean_text(doc['title'][0])
                if re.search(r'[<&$\\]', item['title_after']):
                    item['notes'].append("ADS's title contains markup or LaTeX: check it")
            if item['authors_after'] == item['authors_before']: item['authors_after'] = None
            if item['title_after'] == item['title_before']:     item['title_after'] = None
            if doc and item['authors_after'] is None and item['title_after'] is None:
                item['notes'].append("same as ADS's: nothing to change")
            if r['bibcode'] and doc.get('bibcode') and doc['bibcode'] != r['bibcode']:
                item['notes'].append(f"ADS answered with bibcode {doc['bibcode']}")
        plan.append(item)
        if n % 20 == 0:
            print(f'  {n}/{len(found)}')
        time.sleep(0.15)
    with open(os.path.join(args.out, 'plan.json'), 'w', encoding='utf-8') as f:
        json.dump({'made': datetime.now(timezone.utc).isoformat(), 'db': DB_PATH, 'papers': plan}, f,
                  ensure_ascii=False, indent=1)
    write_html(plan, os.path.join(args.out, 'report.html'))
    dmg = [p for p in plan if p['category'] == 'damaged']
    print(f"damaged: {len(dmg)} ({sum(1 for p in dmg if p['authors_after'] or p['title_after'])} with a repair from ADS); "
          f"only a dotless i: {len(plan) - len(dmg)}")
    print(f"written: {args.out}/report.html and {args.out}/plan.json (nothing in the database was changed)")

def write_html(plan, path):
    esc = lambda s: html.escape(s or '')
    def rows(items):
        out = []
        for p in items:
            for field in ('authors', 'title'):
                after = p[f'{field}_after']
                if after is None and not (field == 'authors' and p['notes']):
                    continue
                out.append(f"<tr><td><b>{esc(p['bibkey'])}</b><br><small>{esc(p['library'])}<br>{esc(p['bibcode'] or p['doi'])}</small></td>"
                           f"<td>{field}</td><td class=b>{esc(p[field + '_before'])}</td>"
                           f"<td class=a>{esc(after) if after is not None else '<i>unchanged</i>'}</td>"
                           f"<td>{esc('; '.join(p['notes']))}</td></tr>")
        return '\n'.join(out)
    dmg = [p for p in plan if p['category'] == 'damaged']; chk = [p for p in plan if p['category'] == 'check']
    head = '<tr><th>Paper</th><th>Field</th><th>Now</th><th>From ADS</th><th>Notes</th></tr>'
    doc = f'''<!doctype html><meta charset="utf-8"><title>BibMan accent repair report</title>
<style>body{{font-family:sans-serif;font-size:13px;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left}}.b{{background:#fff3f3}}.a{{background:#f1fff1}}
small{{color:#666}}</style>
<h2>BibMan accent repair: report only (nothing was changed)</h2>
<p>Made {esc(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}. Author lists from ADS keep the first {MAX_AUTHORS} names, then "et al.".</p>
<h3>Damaged: {len(dmg)} papers (repaired by "apply", except those you name with --skip)</h3>
<table>{head}{rows(dmg)}</table>
<h3>Only a dotless i: {len(chk)} papers (possibly correct, e.g. Turkish names; changed only if you name them with --include)</h3>
<table>{head}{rows(chk)}</table>'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)

def apply(args):
    with open(args.plan, encoding='utf-8') as f:
        plan = json.load(f)['papers']
    skip    = {k.strip() for k in (args.skip or '').split(',') if k.strip()}
    include = {k.strip() for k in (args.include or '').split(',') if k.strip()}
    unknown = (skip | include) - {p['bibkey'] for p in plan}
    if unknown:
        sys.exit(f'Not in the plan (check the spelling): {", ".join(sorted(unknown))}')
    todo = [p for p in plan if (p['authors_after'] is not None or p['title_after'] is not None)
            and p['bibkey'] not in skip and (p['category'] == 'damaged' or p['bibkey'] in include)]
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    undo, changed, stale = [], 0, []
    for p in todo:
        r = conn.execute('SELECT authors, title FROM papers WHERE id=?', (p['id'],)).fetchone()
        if not r or (r['authors'] or '') != p['authors_before'] or (r['title'] or '') != p['title_before']:
            stale.append(p['bibkey']); continue
        undo.append({'id': p['id'], 'bibkey': p['bibkey'], 'authors': r['authors'], 'title': r['title']})
    undo_path = os.path.join(os.path.dirname(os.path.abspath(args.plan)),
                             'undo-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.json')
    with open(undo_path, 'w', encoding='utf-8') as f:           # saved before anything is written
        json.dump(undo, f, ensure_ascii=False, indent=1)
    keep = {u['id'] for u in undo}
    for p in todo:
        if p['id'] not in keep:
            continue
        sets, vals = [], []
        if p['authors_after'] is not None: sets.append('authors=?'); vals.append(p['authors_after'])
        if p['title_after']   is not None: sets.append('title=?');   vals.append(p['title_after'])
        conn.execute(f"UPDATE papers SET {', '.join(sets)}, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                     vals + [p['id']])
        changed += 1
    conn.commit(); conn.close()
    print(f'repaired: {changed}; skipped by you: {len(skip)}; changed since the report, left alone: {len(stale)}'
          + (f' ({", ".join(stale)})' if stale else ''))
    print(f'old values saved in {undo_path} (use "undo --undo {undo_path}" to put them back)')

def undo(args):
    with open(args.undo, encoding='utf-8') as f:
        saved = json.load(f)
    conn = sqlite3.connect(DB_PATH)
    for u in saved:
        conn.execute('UPDATE papers SET authors=?, title=? WHERE id=?', (u['authors'], u['title'], u['id']))
    conn.commit(); conn.close()
    print(f'put back the old authors and titles of {len(saved)} papers')

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('report'); a.add_argument('--out', default='/tmp/accent_repair')
    b = sub.add_parser('apply');  b.add_argument('--plan', required=True); b.add_argument('--skip'); b.add_argument('--include')
    c = sub.add_parser('undo');   c.add_argument('--undo', required=True)
    args = ap.parse_args()
    {'report': report, 'apply': apply, 'undo': undo}[args.cmd](args)
