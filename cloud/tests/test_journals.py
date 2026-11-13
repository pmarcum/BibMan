"""Journals (13 Nov 2026): undefined macros exported as names; the repair pass; the port of Core's table kept in step."""
import json, os, re, sys
H = {'X-BibMan-Credential': 'test_credential_0123456789'}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def test_export_journal_names(server):
    j = server._bib_journal
    assert j('\\apj', True) == '\\apj' and j('\\mnras', True) == '\\mnras' and j('\\icarus', True) == '\\icarus'
    assert j('\\rmp', True) == 'Reviews of Modern Physics' and j('\\sci', True) == 'Science'
    assert j('\\an', True) == 'Astronomische Nachrichten' and j('\\icar', True) == 'Icarus'
    assert j('\\unknownmacro', True) == '\\unknownmacro' and j('Some Journal', True) == 'Some Journal'
    assert j('\\rmp', False) == '\\rmp'                                  # Refs tab: as stored
    c = server.app.test_client()
    c.post('/api/papers/add-manual', json={'title': 'RMP', 'authors': 'Sellwood, J. A.', 'year': '2014', 'journal': '\\rmp',
           'library': 'Extragalactic', '_username': 'pam', 'bibkey': 'sellwood2014x'}, headers=H)
    comp = c.post('/api/export/bib', json={'bibkeys': ['sellwood2014x']}, headers=H).get_json()['bibtex']
    assert 'journal = {Reviews of Modern Physics}' in comp

def test_port_matches_core():
    sys.path.insert(0, HERE); import bibman_repair_accents as R
    gs = open(os.path.join(HERE, '..', 'apps_script', 'BibMan_Core_Library', 'Code.gs'), encoding='utf-8').read()
    block = gs[gs.find('const JOURNAL_PATTERNS = ['):]; block = block[:block.find('];')]
    core = [(rx, m.replace('\\\\', '\\') if m else None) for rx, _, m in re.findall(r"\[/(.+?)/i, (null|'([^']*)')\]", block)]
    assert core == [(rx.pattern, m) for rx, m in R.JOURNAL_PATTERNS]
    stored = dict((k.replace('\\\\', '\\'), v.replace('\\\\', '\\')) for k, v in
                  re.findall(r"'(\\\\\w+)': '([^']*)'", gs[gs.find('const JOURNAL_STORED'):gs.find('function journalForStorage')]))
    assert stored == R.JOURNAL_STORED

def test_journals_pass(server, tmp_path, monkeypatch):
    c = server.app.test_client(); conn = server.get_db_connection()
    add = lambda key, j, bc: c.post('/api/papers/add-manual', json={'title': key, 'authors': 'Doe, J.', 'year': '2016',
          'journal': j, 'bibcode': bc, 'library': 'Extragalactic', '_username': 'pam', 'bibkey': key}, headers=H).get_json()['paper_id']
    falchi = add('falchi2016', '\\an', '2016SciA....2E0377F'); real = add('real2008', '\\an', '2008AN....329..619G')
    apj = add('savoy2009', '\\afz', '2009ApJ...706...21S'); gone = add('vandyk2005', '\\an', '')
    fine = add('ok2010', '\\apj', '2010ApJ...1....1O')
    sys.path.insert(0, os.path.dirname(server.__file__)); import bibman_repair_accents as R
    monkeypatch.setattr(R, 'DB_PATH', os.environ['DB_PATH'])
    pubs = {'2016SciA....2E0377F': 'Science Advances', '2008AN....329..619G': 'Astronomische Nachrichten',
            '2009ApJ...706...21S': 'The Astrophysical Journal'}
    class Resp:
        def __init__(self, d): self.status_code, self._d = 200, d
        def raise_for_status(self): pass
        def json(self): return {'response': {'docs': self._d}}
    class Session:
        def get(self, url, params=None, headers=None, timeout=None):
            code = params['q'].split('"')[1]
            return Resp([{'bibcode': code, 'pub': pubs[code]}] if code in pubs else [])
    import requests; monkeypatch.setattr(requests, 'Session', Session); monkeypatch.setattr(R.time, 'sleep', lambda s: None)
    monkeypatch.setenv('ADS_TOKEN', 't'); out = tmp_path / 'j'
    R.journals_pass(type('A', (), {'out': str(out)}))
    plan = {p['bibkey']: p for p in json.load(open(out / 'journals-plan.json'))['papers']}
    assert {'falchi2016', 'real2008', 'savoy2009', 'vandyk2005'} <= set(plan) and 'ok2010' not in plan  # \apj is defined
    assert plan['falchi2016']['journal_after'] == 'Science Advances' and plan['savoy2009']['journal_after'] == '\\apj'
    assert plan['real2008']['journal_after'] == 'Astronomische Nachrichten' and plan['vandyk2005']['category'] == 'check'
    R.apply(type('A', (), {'plan': str(out / 'journals-plan.json'), 'skip': '', 'include': ''}))
    get = lambda pid: conn.execute('SELECT journal FROM papers WHERE id=?', (pid,)).fetchone()[0]
    assert get(falchi) == 'Science Advances' and get(apj) == '\\apj' and get(gone) == '\\an' and get(fine) == '\\apj'
    R.undo(type('A', (), {'undo': str(sorted(out.glob('undo-*.json'))[-1])}))
    assert get(falchi) == '\\an' and get(apj) == '\\afz'
