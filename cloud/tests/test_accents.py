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
    assert '$α$' in out and 'doi = {10.1/ü}' in out                    # math and address fields untouched
    assert out.startswith('@ARTICLE{k,') and out.endswith('}')
    assert server.latex_ascii_entry('@misc{a, title={plain}}') == '@misc{a, title={plain}}'
    assert not re.search(r'[^\x00-\x7f]', out.replace('$α$', '').replace('10.1/ü', ''))

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
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ("Infante-S\\ínz, Ra\\' ́and Mart\\'ıánd", bad))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Yıldız, M.', tur))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Bád, S.', skp))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Góne, G.', gone))
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Sta\u0301le, T.', stale))
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
    assert plan['dmg2019']['authors_after'] == ' and '.join(f'Author{i}, A.' for i in range(1, 11)) + ' and et al.'
    assert plan['tur2020']['category'] == 'check' and plan['tur2020']['authors_after'] is None   # same as ADS's
    assert plan['gone2020']['authors_after'] is None and 'not found on ADS' in plan['gone2020']['notes'][0]
    assert 'Damaged: ' in (out / 'report.html').read_text()
    before = conn.execute('SELECT authors FROM papers WHERE id=?', (bad,)).fetchone()[0]
    assert 'Ra\\' in before                                                       # report changed nothing
    # a paper edited after the report is left alone
    conn.execute('UPDATE papers SET authors=? WHERE id=?', ('Hand Fixed, T.', stale)); conn.commit()
    R.apply(type('A', (), {'plan': str(out / 'plan.json'), 'skip': 'skip2020', 'include': ''}))
    get = lambda pid: conn.execute('SELECT authors FROM papers WHERE id=?', (pid,)).fetchone()[0]
    assert get(bad).startswith('Author1, A. and') and get(skp) == 'Bád, S.' and get(stale) == 'Hand Fixed, T.'
    undo = sorted(out.glob('undo-*.json'))[-1]
    R.undo(type('A', (), {'undo': str(undo)}))
    assert get(bad) == before
