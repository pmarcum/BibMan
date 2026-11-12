#!/usr/bin/env python3
r"""
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
                                              [--fix fixes.json]
     --fix gives corrected values where ADS's own are unusable, as {"bibkey": {"authors": "...", "title": "..."}}: they
     replace the plan's values for those papers (which are then repaired even if listed as "only a dotless i").
  T. titles (12 Nov 2026): the same move decoded LaTeX in titles too ({\ensuremath{\sigma}} -> \ensuremathσ,
     \odot -> ødot, 10$^{11}$ -> 10$^11$). "titles" compares candidate titles with the title in ADS's BibTeX export
     (LaTeX, kept as ADS writes it, except that ADS's lowered tilde \raisebox{-0.5ex}\textasciitilde becomes
     $\sim$, $\lesssim$, $\gtrsim$ or $\simeq$) and writes titles-report.html and titles-plan.json; "apply --plan .../titles-plan.json"
     then works as above. Titles that differ from ADS's only in LaTeX or symbols are repaired; titles whose words
     differ are changed only when named with --include; papers not found on ADS are only listed.
       ADS_TOKEN=... python bibman_repair_accents.py titles --out /tmp/accent_repair
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

LATEX_ACCENT   = re.compile(r"\\[`'^\"~=.]|\\[uvHcdbtrk]\s*\{|\\(?:i|j|l|L|o|O|ss|ae|AE|aa|AA|oe|OE)(?![A-Za-z])")

def classify(text):
    if DAMAGE.search(text or ''):       return 'damaged'
    if LATEX_ACCENT.search(text or ''): return 'latex'
    if DOTLESS_I.search(text or ''):    return 'check'
    return None

def names_from_latex(s):
    """Author names written in LaTeX (C\\^{o}t\\'{e}) as plain UTF-8 (Côté), as the server's names_from_latex."""
    from pylatexenc.latex2text import LatexNodes2Text
    return clean_text(LatexNodes2Text(math_mode='verbatim', strict_latex_spaces=True).latex_to_text(s).replace('\u00a0', ' '))

def ads_lookup(session, token, bibcode, doi):
    """ADS's record for a paper, by bibcode (its own or an older one, such as the arXiv bibcode it had before it was
    published), else by DOI: {bibcode, author, title} or None."""
    for q in ([f'identifier:"{bibcode}"'] if bibcode else []) + ([f'doi:"{doi}"'] if doi else []):
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

ADS_EXPORT_URL = 'https://api.adsabs.harvard.edu/v1/export/bibtex'
MIGRATED_BEFORE = '2026-04-16'      # papers created before BibMan went live came through the March-April move
TITLE_CANDIDATE = re.compile(r'[\\$^_~<>]|[^\x00-\x7f]')
# Clearly broken or unsafe for LaTeX, in any paper: a command glued to what follows (\ensuremathσ), \odot read as
# \o + dot, a backslash before a non-ASCII letter, ^ or _ followed by several characters without braces, HTML from
# ADS's plain titles, and ^ _ ~ outside math
TITLE_BROKEN = re.compile(r'\\ensuremath(?!\s*\{)|ødot|\\[^\x00-\x7f]|[\^_][^{\s$\\][^\s${}]|&lt;|&gt;|&amp;|</?(?:SUB|SUP|sub|sup)>')

def _outside_math_unsafe(t):
    return bool(re.search(r'[\^_~]', re.sub(r'(?<!\\)\$[^$]*\$', '', t)))

def bibtex_field_value(entry, name):
    """One field of a BibTeX entry, never decoded: outer "..." or {...} and one more pair spanning it all removed
    (as Core's bibtexFieldValue)."""
    m = re.search(r'(?:^|[,{\s])' + name + r'\s*=\s*', entry, re.I)
    if not m:
        return ''
    i = m.end(); open_ = entry[i:i + 1]
    if open_ in ('{', '"'):
        depth, j = 0, i
        while j < len(entry):
            ch = entry[j]
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if open_ == '{' and depth == 0: break
            elif ch == '"' and open_ == '"' and j > i and depth == 0: break
            j += 1
        value = entry[i + 1:j]
    else:
        value = re.match(r'[^,}\s]*', entry[i:]).group(0)
    value = value.strip()
    if value.startswith('{') and value.endswith('}'):
        depth, spans = 0, True
        for j, ch in enumerate(value):
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and j < len(value) - 1: spans = False; break
        if spans: value = value[1:-1]
    return re.sub(r'\s+', ' ', value).strip()

_ADS_TILDE = r'\\raisebox\{-0\.5ex\}\\textasciitilde'

def ads_title_symbols(t):
    r"""ADS writes ∼ as \raisebox{-0.5ex}\textasciitilde (a lowered tilde) in many older titles; BibMan stores it as math
    instead: <∼ → $\lesssim$, >∼ → $\gtrsim$, ∼= → $\simeq$, ∼ → $\sim$. Nothing else is changed (as Core's
    adsTitleSymbols)."""
    t = re.sub('<' + _ADS_TILDE, lambda m: r'$\lesssim$', t or '')
    t = re.sub('>' + _ADS_TILDE, lambda m: r'$\gtrsim$', t)
    t = re.sub(_ADS_TILDE + '=', lambda m: r'$\simeq$', t)
    return re.sub(_ADS_TILDE, lambda m: r'$\sim$', t)

def ads_latex_titles(session, token, bibcodes):
    """{bibcode: title} from ADS's BibTeX export, 100 at a time."""
    out = {}
    for k in range(0, len(bibcodes), 100):
        chunk = bibcodes[k:k + 100]
        for attempt in range(3):
            r = session.post(ADS_EXPORT_URL, json={'bibcode': chunk},
                             headers={'Authorization': f'Bearer {token}'}, timeout=60)
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1)); continue
            r.raise_for_status(); break
        for entry in re.split(r'\n(?=@)', '\n' + r.json().get('export', '')):
            m = re.match(r'\s*@\w+\{([^,]+),', entry)
            if m:
                out[m.group(1).strip()] = ads_title_symbols(bibtex_field_value(entry, 'title'))
        time.sleep(0.3)
    return out

def _words(t):
    """A title's words for comparing: LaTeX and markup read as text, accents and case ignored."""
    try:
        from pylatexenc.latex2text import LatexNodes2Text
        t = LatexNodes2Text(math_mode='text').latex_to_text(t)
    except Exception:
        pass
    t = unicodedata.normalize('NFKD', html.unescape(t))
    return re.sub(r'[^0-9a-z]+', ' ', ''.join(c for c in t if not unicodedata.combining(c)).lower()).strip()

def titles(args):
    token = os.environ.get('ADS_TOKEN', '').strip()
    if not token:
        sys.exit('Set ADS_TOKEN first (your NASA ADS API token).')
    import requests, difflib
    os.makedirs(args.out, exist_ok=True)
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True); conn.row_factory = sqlite3.Row
    rows = conn.execute('''SELECT p.id, p.bibkey, p.bibcode, p.doi, p.title, p.authors, p.created_at, l.name AS library
                             FROM papers p LEFT JOIN libraries l ON l.id = p.library_id ORDER BY p.bibkey''').fetchall()
    conn.close()
    cands = []
    for r in rows:
        t = r['title'] or ''
        if not TITLE_CANDIDATE.search(t):
            continue
        broken = bool(TITLE_BROKEN.search(t)) or _outside_math_unsafe(t)
        migrated = (r['created_at'] or '') < MIGRATED_BEFORE
        if broken or migrated:
            cands.append((r, broken))
    session = requests.Session()
    print(f'{len(cands)} candidate titles; asking ADS ...')
    # bibcodes for papers that only have a DOI
    bib = {}
    for r, _ in cands:
        if r['bibcode']:
            bib[r['id']] = r['bibcode']
        elif r['doi']:
            try:
                d = ads_lookup(session, token, None, r['doi']); bib[r['id']] = (d or {}).get('bibcode', '')
            except Exception:
                bib[r['id']] = ''
    found = ads_latex_titles(session, token, sorted({b for b in bib.values() if b}))
    # a stored arXiv bibcode is only an older name once the paper is published: ADS exports it under the journal one
    newer = {}
    for b in sorted({b for b in bib.values() if b and b not in found}):
        try:
            d = ads_lookup(session, token, b, None)
        except Exception:
            d = None
        if d and d.get('bibcode') and d['bibcode'] != b:
            newer[b] = d['bibcode']
    if newer:
        more = ads_latex_titles(session, token, sorted(set(newer.values())))
        found.update({old: more[b] for old, b in newer.items() if b in more})
    plan = []
    for r, broken in cands:
        before = r['title'] or ''
        ads_t = found.get(bib.get(r['id'], ''), '')
        item = {'id': r['id'], 'bibkey': r['bibkey'], 'library': r['library'], 'bibcode': bib.get(r['id'], ''),
                'doi': r['doi'] or '', 'authors_before': r['authors'] or '', 'title_before': before,
                'authors_after': None, 'title_after': None, 'notes': []}
        if not ads_t:
            item['category'] = 'notfound'
            item['notes'].append('not found on ADS: left unchanged' + (' (title looks broken: needs your decision)' if broken else ''))
            if broken: plan.append(item)
            continue
        if re.sub(r'\s+', ' ', ads_t).strip() == re.sub(r'\s+', ' ', before).strip():
            continue                                               # already ADS's own LaTeX title
        sim = difflib.SequenceMatcher(None, _words(before), _words(ads_t)).ratio()
        item['title_after'] = ads_t
        item['category'] = 'title' if sim >= 0.85 else 'title-check'
        item['notes'].append(f'words {round(sim * 100)}% the same' + ('' if sim >= 0.85 else ': check it is the same paper'))
        if broken: item['notes'].append('stored title is broken or unsafe for LaTeX')
        if bib.get(r['id']) in newer: item['notes'].append(f"ADS now lists it as {newer[bib[r['id']]]}")
        plan.append(item)
    with open(os.path.join(args.out, 'titles-plan.json'), 'w', encoding='utf-8') as f:
        json.dump({'made': datetime.now(timezone.utc).isoformat(), 'db': DB_PATH, 'papers': plan}, f, ensure_ascii=False, indent=1)
    write_titles_html(plan, os.path.join(args.out, 'titles-report.html'))
    n = lambda c: sum(1 for p in plan if p['category'] == c)
    print(f"to repair: {n('title')}; words differ (your decision): {n('title-check')}; broken but not on ADS: {n('notfound')}")
    print(f"written: {args.out}/titles-report.html and {args.out}/titles-plan.json (nothing in the database was changed)")

def write_titles_html(plan, path):
    esc = lambda s: html.escape(s or '')
    def rows(items):
        return '\n'.join(f"<tr><td><b>{esc(p['bibkey'])}</b><br><small>{esc(p['library'])}<br>{esc(p['bibcode'] or p['doi'])}</small></td>"
                         f"<td class=b>{esc(p['title_before'])}</td><td class=a>{esc(p['title_after']) if p['title_after'] else '<i>unchanged</i>'}</td>"
                         f"<td>{esc('; '.join(p['notes']))}</td></tr>" for p in items)
    head = '<tr><th>Paper</th><th>Title now</th><th>ADS BibTeX title</th><th>Notes</th></tr>'
    part = lambda c: [p for p in plan if p['category'] == c]
    doc = f'''<!doctype html><meta charset="utf-8"><title>BibMan title repair report</title>
<style>body{{font-family:sans-serif;font-size:13px;margin:16px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left;font-family:monospace}}.b{{background:#fff3f3}}.a{{background:#f1fff1}}
small{{color:#666}}</style>
<h2>BibMan title repair: report only (nothing was changed)</h2>
<p>Made {esc(datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))}. Titles are shown as stored (LaTeX as written); the new ones are ADS's BibTeX titles, with ADS's lowered tilde written as $\\sim$, $\\lesssim$, $\\gtrsim$ or $\\simeq$.</p>
<h3>To repair: {len(part('title'))} titles (differ from ADS's only in LaTeX or symbols; changed by "apply", except those you name with --skip)</h3>
<table>{head}{rows(part('title'))}</table>
<h3>Words differ: {len(part('title-check'))} titles (changed only if you name them with --include)</h3>
<table>{head}{rows(part('title-check'))}</table>
<h3>Broken but not found on ADS: {len(part('notfound'))} titles (left unchanged; for your decision)</h3>
<table>{head}{rows(part('notfound'))}</table>'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)

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
    # Author lists written in LaTeX accents (papers added before Core 14) but not damaged: converted to UTF-8 here,
    # all names kept, no ADS needed (titles may hold math, so they are left alone)
    for r, a, t in found:
        if a == 'latex' and t != 'damaged':
            after = names_from_latex(r['authors'])
            if after != r['authors']:
                plan.append({'id': r['id'], 'bibkey': r['bibkey'], 'library': r['library'], 'category': 'latex',
                             'bibcode': r['bibcode'] or '', 'doi': r['doi'] or '', 'authors_before': r['authors'],
                             'title_before': r['title'] or '', 'authors_after': after, 'title_after': None, 'notes': []})
    found = [(r, a, t) for r, a, t in found if 'damaged' in (a, t) or (a == 'check' and t != 'latex') or t == 'check']
    found = [(r, a, t) for r, a, t in found if not any(p['id'] == r['id'] for p in plan)]
    print(f"{len([p for p in plan if p['category'] == 'latex'])} author lists with LaTeX accents to convert; "
          f"{len(found)} papers to look up on ADS ...")
    for n, (r, a_cls, t_cls) in enumerate(found, 1):
        a_cls = None if a_cls == 'latex' else a_cls; t_cls = None if t_cls == 'latex' else t_cls
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
                item['title_after'] = clean_text(html.unescape(doc['title'][0]))
                if re.search(r'[<>&$\\~^_]', item['title_after']):   # ADS writes e.g. "z ~ 7", "<~", "10^8 M_☉"
                    item['notes'].append("ADS's title has symbols LaTeX would misread (~ ^ _ < >): check it")
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
    print(f"LaTeX accents to convert: {sum(1 for p in plan if p['category'] == 'latex')}; damaged: {len(dmg)} ({sum(1 for p in dmg if p['authors_after'] or p['title_after'])} with a repair from ADS); "
          f"only a dotless i: {sum(1 for p in plan if p['category'] == 'check')}")
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
    ltx = [p for p in plan if p['category'] == 'latex']
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
<table>{head}{rows(chk)}</table>
<h3>LaTeX accents: {len(ltx)} author lists written as e.g. C\\^{{o}}t\\'{{e}}, converted to plain UTF-8 with all names kept,
no ADS needed (changed by "apply", except those you name with --skip)</h3>
<table>{head}{rows(ltx)}</table>'''
    with open(path, 'w', encoding='utf-8') as f:
        f.write(doc)

def apply(args):
    with open(args.plan, encoding='utf-8') as f:
        plan = json.load(f)['papers']
    skip    = {k.strip() for k in (args.skip or '').split(',') if k.strip()}
    include = {k.strip() for k in (args.include or '').split(',') if k.strip()}
    fixes   = {}
    if getattr(args, 'fix', None):
        with open(args.fix, encoding='utf-8') as f:
            fixes = json.load(f)
    unknown = (skip | include | set(fixes)) - {p['bibkey'] for p in plan}
    if unknown:
        sys.exit(f'Not in the plan (check the spelling): {", ".join(sorted(unknown))}')
    for p in plan:                                  # corrected values given by hand win over ADS's
        for field in ('authors', 'title'):
            if field in fixes.get(p['bibkey'], {}):
                p[f'{field}_after'] = clean_text(fixes[p['bibkey']][field])
        if p['bibkey'] in fixes:
            include.add(p['bibkey'])
    todo = [p for p in plan if (p['authors_after'] is not None or p['title_after'] is not None)
            and p['bibkey'] not in skip and (p['category'] in ('damaged', 'latex', 'title') or p['bibkey'] in include)]
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    undo, changed, stale = [], 0, []
    for p in todo:
        r = conn.execute('SELECT authors, title FROM papers WHERE id=?', (p['id'],)).fetchone()
        if not r or (r['authors'] or '') != p['authors_before'] or (r['title'] or '') != p['title_before']:
            stale.append(p['bibkey']); continue
        undo.append({'id': p['id'], 'bibkey': p['bibkey'], 'authors': r['authors'], 'title': r['title']})
    undo_path = os.path.join(os.path.dirname(os.path.abspath(args.plan)),
                             'undo-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f') + '.json')   # never overwrites one
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
    b.add_argument('--fix')
    c = sub.add_parser('undo');   c.add_argument('--undo', required=True)
    d = sub.add_parser('titles'); d.add_argument('--out', default='/tmp/accent_repair')
    args = ap.parse_args()
    {'report': report, 'apply': apply, 'undo': undo, 'titles': titles}[args.cmd](args)
