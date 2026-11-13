"""Accents (12 Nov 2026): plain UTF-8 stored, braced LaTeX in the exports BibTeX reads, the repair script."""
import json, os, re, subprocess, sys
H = {'X-BibMan-Credential': 'test_credential_0123456789'}

def test_clean_text_and_names(server):
    assert server.clean_text('Vı́lchez') == 'Vílchez'                   # dotless i + accent mark
    assert server.clean_text('Rom' + 'á' + 'n') == 'Román'                  # letter + accent mark
    assert server.clean_text('Yıldız') == 'Yıldız'                               # a real dotless i stays
    assert server.names_from_latex(r"{Rom{\'a}n}, Javier and Mart{\'\i}n, R. and M{\"u}ller, O.") == \
        'Román, Javier and Martín, R. and Müller, O.'
    assert server.names_from_latex('Plain, Name') == 'Plain, Name'

def test_latex_ascii_entry(server):
    e = ('@ARTICLE{k,\n author = {Infante-Sáinz, Raúl and Yıldız, M.},\n title = "{Hα, 10–20 $α$}",\n'
         ' doi = {10.1/ü},\n year = 2019,\n}')
    out = server.latex_ascii_entry(e)
    assert "Infante-S{\\'a}inz, Ra{\\'u}l and Y{\\i}ld{\\i}z" in out
    assert '{\\ensuremath{\\alpha}}' in out and '{\\textendash}' in out
    assert '${\\ensuremath{\\alpha}}$' in out and 'doi = {10.1/ü}' in out   # symbols in math as LaTeX; addresses untouched
    assert out.startswith('@ARTICLE{k,') and out.endswith('}')
    assert server.latex_ascii_entry('@misc{a, title={plain}}') == '@misc{a, title={plain}}'
    assert not re.search(r'[^\x00-\x7f]', out.replace('10.1/ü', ''))

def test_symbols_pylatexenc_lacks(server):
    """Characters found in the library that pylatexenc has no LaTeX for, and symbols inside $...$ (12 Nov 2026)."""
    v = server._latex_value
    assert v('M$_{☉}$ and M☉') == 'M$_{{\\ensuremath{\\odot}}}$ and M{\\ensuremath{\\odot}}'
    assert v('u$^{′}$ and K′') == "u$^{{\\ensuremath{\\prime}}}$ and K{'}"
    assert v('M★ Size─Stellar') == 'M{\\ensuremath{\\star}} Size{\\textendash}Stellar'
    assert v('Coteș, Ștefan') == 'Cote{\\c{s}}, {\\c{S}}tefan'
    assert v('$x é$') == '$x é$'                         # an accented letter is not math: left for the author to see
    assert v('z $\\lesssim$ 2, 10$^{11}$') == 'z $\\lesssim$ 2, 10$^{11}$'      # ASCII math exactly as stored

def _add(c, title, authors, lib='Extragalactic', **kw):
    return c.post('/api/papers/add-manual', json={'title': title, 'authors': authors, 'year': '2020', 'library': lib,
                                                  '_username': 'pam', **kw}, headers=H).get_json()

def test_stored_as_utf8_and_exports(server):
    c = server.app.test_client()
    p = _add(c, 'Accented títle', r"{Rom{\'a}n}, Javier and Mart{\'\i}n, R.", bibkey='roman2020acc')
    row = server.get_db_connection().execute('SELECT authors, title FROM papers WHERE id=?', (p['paper_id'],)).fetchone()
    assert row['authors'] == 'Román, Javier and Martín, R.' and row['title'] == 'Accented títle'
    compile_ = c.post('/api/export/bib', json={'bibkeys': ['roman2020acc']}, headers=H).get_json()['bibtex']
    assert "Rom{\\'a}n, Javier and Mart{\\'\\i}n" in compile_ and 't{\\\'\\i}tle' in compile_
    plain = c.get('/api/export/bib-text?library=Extragalactic', headers=H).get_data(as_text=True)
    drive = c.get('/api/export/bib-text?library=Extragalactic&latex=1', headers=H).get_data(as_text=True)
    assert 'Román' in plain and 'Román' not in drive and "Rom{\\'a}n" in drive
    assert drive.startswith('% BibMan export - ') and plain.startswith('% BibMan export — ')
    # editing through the dashboard keeps UTF-8 as well
    c.patch(f"/api/papers/{p['paper_id']}", json={'authors': r'M{\"u}ller, O.', '_username': 'pam'}, headers=H)
    assert server.get_db_connection().execute('SELECT authors FROM papers WHERE id=?', (p['paper_id'],)).fetchone()[0] == 'Müller, O.'

def test_duplicates_ignore_accent_form(server):
    c = server.app.test_client()
    first = _add(c, 'A study of accent forms in names', r"Rom\'{a}n, J. and Smith, A.", journal='ApJ', volume='901', pages='12')
    second = _add(c, 'A study of accent forms in names', 'Román, J. and Smith, A.', journal='ApJ', volume='901', pages='12')
    assert first.get('paper_id') and second.get('duplicate') is True

def test_repair_script(server, tmp_path, monkeypatch):
    """report finds damaged papers and proposes ADS's names; apply writes them (not skipped or changed ones); undo."""
    c = server.app.test_client(); db = os.environ['DB_PATH']
    conn = server.get_db_connection()
    bad = _add(c, 'Damaged one', 'x', bibkey='dmg2019', bibcode='2019A&A...621A.133B')['paper_id']
    tur = _add(c, 'Turkish', 'y', bibkey='tur2020', bibcode='2020X')['paper_id']
    skp = _add(c, 'Skip me', 'z', bibkey='skip2020', bibcode='2020S')['paper_id']
    gone = _add(c, 'Not on ADS', 'w', bibkey='gone2020', bibcode='2020G')['paper_id']
    stale = _add(c, 'Edited later', 'v', bibkey='stale2020', bibcode='2020T')['paper_id']
    ltx = _add(c, 'LaTeX names', 'u', bibkey='ltx2025', bibcode='2025L')['paper_id']
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ("Infante-S\\ínz, Ra\\' ́and Mart\\'ıánd", bad))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Yıldız, M.', tur))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Bád, S.', skp))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Góne, G.', gone))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Sta\u0301le, T.', stale))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ("Sola, E. and C\\^{o}t\\'{e}, P. and Y\u0131ld\u0131z, M. K. and M\\\"{u}ller, O.", ltx))
    conn.commit()
    sys.path.insert(0, os.path.dirname(server.__file__)); import bibman_repair_accents as R
    monkeypatch.setattr(R, 'DB_PATH', db)
    ads = {'2019A&A...621A.133B': {'author': [f'Author{i}, A.' for i in range(1, 12)], 'title': ['Damaged one']},
           '2020X': {'author': ['Yıldız, M.'], 'title': ['Turkish']}, '2020S': {'author': ['Bád, S.'], 'title': ['Skip me']},
           '2020T': {'author': ['Stále, T.'], 'title': ['Edited later']}}
    class Resp:
        def __init__(self, docs): self.status_code, self._d = 200, docs
        def raise_for_status(self): pass
        def json(self): return {'response': {'docs': self._d}}
    class Session:
        def get(self, url, params=None, headers=None, timeout=None):
            code = params['q'].split('"')[1]
            return Resp([{'bibcode': code, **ads[code]}] if code in ads else [])
    import requests; monkeypatch.setattr(requests, 'Session', Session); monkeypatch.setattr(R.time, 'sleep', lambda s: None)
    monkeypatch.setenv('ADS_TOKEN', 't')
    out = tmp_path / 'rep'
    R.report(type('A', (), {'out': str(out)}))
    plan = {p['bibkey']: p for p in json.load(open(out / 'plan.json'))['papers']}
    assert plan['dmg2019']['category'] == 'damaged'
    assert plan['dmg2019']['authors_after'] == ' and '.join(f'Author{i}, A.' for i in range(1, 12))   # every name (13 Nov 2026)
    assert plan['tur2020']['category'] == 'check' and plan['tur2020']['authors_after'] is None   # same as ADS's
    assert plan['ltx2025']['category'] == 'latex' and plan['ltx2025']['authors_after'] == 'Sola, E. and Côté, P. and Yıldız, M. K. and Müller, O.'
    assert plan['gone2020']['authors_after'] is None and 'not found on ADS' in plan['gone2020']['notes'][0]
    assert 'Damaged: ' in (out / 'report.html').read_text()
    before = conn.execute('SELECT authors FROM papers WHERE id=?', (bad,)).fetchone()[0]
    assert 'Ra\\' in before                                                       # report changed nothing
    # a paper edited after the report is left alone
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Hand Fixed, T.', stale)); conn.commit()
    R.apply(type('A', (), {'plan': str(out / 'plan.json'), 'skip': 'skip2020', 'include': ''}))
    get = lambda pid: conn.execute('SELECT authors FROM papers WHERE id=?', (pid,)).fetchone()[0]
    assert get(bad).startswith('Author1, A. and') and get(skp) == 'Bád, S.' and get(stale) == 'Hand Fixed, T.'
    assert get(ltx) == 'Sola, E. and Côté, P. and Yıldız, M. K. and Müller, O.'
    undo = sorted(out.glob('undo-*.json'))[-1]
    # --fix: corrected values given by hand win over ADS's, and include a paper the plan only lists for checking
    import json as _j; fx = tmp_path / 'fixes.json'
    _j.dump({'tur2020': {'authors': 'Yıldız, Mustafa K.'}}, open(fx, 'w', encoding='utf-8'), ensure_ascii=False)
    R.apply(type('A', (), {'plan': str(out / 'plan.json'), 'skip': '', 'include': '', 'fix': str(fx)}))
    assert get(tur) == 'Yıldız, Mustafa K.'
    R.undo(type('A', (), {'undo': str(undo)}))
    assert get(bad) == before

def test_titles_pass(server, tmp_path, monkeypatch):
    """Titles decoded by the migration are compared with ADS's BibTeX titles and repaired verbatim (12 Nov 2026)."""
    c = server.app.test_client(); conn = server.get_db_connection(); db = os.environ['DB_PATH']
    sys.path.insert(0, os.path.dirname(server.__file__)); import bibman_repair_accents as R
    monkeypatch.setattr(R, 'DB_PATH', db)
    ads_bern = (r'Curvature in the colour-magnitude relation but not in colour-{\ensuremath{\sigma}}: major dry mergers '
                r'at M$_{*}$ {\ensuremath{>}} 2 {\texttimes} 10$^{11}$ M$_{\ensuremath{\odot}}$?')
    papers = {   # bibkey: (stored title, created, bibcode, ADS's BibTeX title or None)
        'bern2011':  ('Curvature in the colour-magnitude relation but not in colour-\\ensuremathσ: major dry mergers at '
                      'M$_*$ > 2 × 10$^11$ M$_\\ensuremathødot$?', '2022-01-24', '2011MNRAS.412..684B', ads_bern),
        'same2010':  (r'A {\it plain} $z\sim2$ title', '2020-01-01', '2010S', r'A {\it plain} $z\sim2$ title'),
        'other2010': ('Völlig anders σ', '2020-01-01', '2010O', r'Something {\ensuremath{\sigma}} entirely unrelated here'),
        'newok2026': ('Hα clean UTF-8 title', '2026-06-01', '2026N', r'H{\ensuremath{\alpha}} clean'),
        'newbad2026': ('Black hole of 10^8 M_☉', '2026-06-01', '2026B', r'Black hole of 10$^{8}$ M$_{\ensuremath{\odot}}$'),
        'lost2010':  ('Broken \\ensuremathσ title', '2020-01-01', '2010L', None),
        'arxiv2010': ('Mergers at z \\ensuremath∼ 1', '2020-01-01', '2009arXiv0901.0001M', None),   # stored arXiv bibcode
    }
    ids = {}
    for k, (t, created, bc, _) in papers.items():
        ids[k] = _add(c, 'x' + k, 'A, B.', bibkey=k, bibcode=bc)['paper_id']
        conn.execute('UPDATE papers SET title=?, created_at=? WHERE id=?', (t, created, ids[k])); conn.commit()
    ads = {bc: t for (_, _, bc, t) in papers.values() if t}
    ads['2010A&A...500..705M'] = r'Mergers at z {\textasciitilde} 1'                # ADS knows it by its journal bibcode
    class Resp:
        def __init__(self, d): self.status_code, self._d = 200, d
        def raise_for_status(self): pass
        def json(self): return self._d
    class Session:
        def post(self, url, json=None, headers=None, timeout=None):
            return Resp({'export': '\n\n'.join(f'@ARTICLE{{{b},\n  author = {{X}},\n   title = "{{{ads[b]}}}",\n  year = 2010,\n}}'
                                               for b in json['bibcode'] if b in ads)})
        def get(self, url, params=None, headers=None, timeout=None):
            docs = [{'bibcode': '2010A&A...500..705M'}] if params['q'] == 'identifier:"2009arXiv0901.0001M"' else []
            return Resp({'response': {'docs': docs}})
    import requests; monkeypatch.setattr(requests, 'Session', Session); monkeypatch.setattr(R.time, 'sleep', lambda s: None)
    monkeypatch.setenv('ADS_TOKEN', 't'); out = tmp_path / 't'
    R.titles(type('A', (), {'out': str(out)}))
    plan = {p['bibkey']: p for p in json.load(open(out / 'titles-plan.json'))['papers']}
    assert plan['bern2011']['category'] == 'title' and plan['bern2011']['title_after'] == ads_bern
    assert 'same2010' not in plan and 'newok2026' not in plan                 # identical / clean and not migrated
    assert plan['other2010']['category'] == 'title-check'                     # words differ: your decision
    assert plan['newbad2026']['category'] == 'title'                          # unsafe for LaTeX, any paper
    assert plan['lost2010']['category'] == 'notfound' and plan['lost2010']['title_after'] is None
    assert plan['arxiv2010']['category'] == 'title' and plan['arxiv2010']['title_after'] == r'Mergers at z {\textasciitilde} 1'
    assert 'ADS now lists it as 2010A&A...500..705M' in plan['arxiv2010']['notes']
    R.apply(type('A', (), {'plan': str(out / 'titles-plan.json'), 'skip': '', 'include': '', 'fix': None}))
    get = lambda k: conn.execute('SELECT title FROM papers WHERE id=?', (ids[k],)).fetchone()[0]
    assert get('bern2011') == ads_bern and get('other2010') == 'Völlig anders σ' and get('lost2010').startswith('Broken')
    # and it compiles: the export leaves the LaTeX as it is
    ex = c.post('/api/export/bib', json={'bibkeys': ['bern2011']}, headers=H).get_json()['bibtex']
    assert ads_bern in ex

def test_titles_braced_for_bibtex(server):
    """The exports BibTeX reads put a title in a second pair of braces so styles keep its capitals (12 Nov 2026);
    the Refs-tab export (UTF-8, for display) is as before."""
    c = server.app.test_client(); conn = server.get_db_connection()
    c.post('/api/libraries', json={'name': 'Braces', '_username': 'pam'}, headers=H)
    _add(c, r'The SAURON project at z $\sim$ 2', 'Doe, J.', lib='Braces', bibkey='doe2020sauron')
    comp = c.post('/api/export/bib', json={'bibkeys': ['doe2020sauron']}, headers=H).get_json()['bibtex']
    assert r'title   = {{The SAURON project at z $\sim$ 2}},' in comp
    drive = c.get('/get_bib?library=Braces&latex=1').get_data(as_text=True)
    assert r'title   = {{The SAURON project at z $\sim$ 2}},' in drive
    refs = c.get('/get_bib?library=Braces&tags=1').get_data(as_text=True)
    assert r'title   = {The SAURON project at z $\sim$ 2},' in refs

def test_ascii_relations_in_text(server):
    """< > | outside math are written as text commands: the default OT1 encoding prints them as ¡ ¿ — (12 Nov 2026)."""
    v = server._latex_value
    assert v('M$_{*}$ > 2 and z < 1 | x') == r'M$_{*}$ {\textgreater} 2 and z {\textless} 1 {\textbar} x'
    assert v('$M_* > 2$ and $z<1$') == '$M_* > 2$ and $z<1$'                      # math exactly as stored
    assert v(r'z {\ensuremath{<}} 1 and {\ensuremath{\mathrm{a}>b}} > c') == \
        r'z {\ensuremath{<}} 1 and {\ensuremath{\mathrm{a}>b}} {\textgreater} c'    # \ensuremath is math too
    assert v('Smith & Jones <a>') == r'Smith \& Jones {\textless}a{\textgreater}'

def test_ascii_only_entry_with_relations(server):
    """An entry with no non-ASCII character still gets < > | written as text commands; addresses untouched."""
    e = '@article{k,\n  title   = {{Galaxies at z < 1}},\n  url     = {https://x.org/?a=1|2},\n}'
    out = server.latex_ascii_entry(e)
    assert r'{{Galaxies at z {\textless} 1}}' in out and 'https://x.org/?a=1|2' in out
    assert server.latex_ascii_entry('@article{k,\n  title = {Plain},\n}') == '@article{k,\n  title = {Plain},\n}'
