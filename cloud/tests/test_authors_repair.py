"""The full-author-list pass of the repair script (13 Nov 2026): report first, apply, --fix outside the plan, undo."""
import json, os, sys
H = {'X-BibMan-Credential': 'test_credential_0123456789'}

def _add(c, title, authors, **kw):
    return c.post('/api/papers/add-manual', json={'title': title, 'authors': authors, 'year': '2020', 'library':
                  'Extragalactic', '_username': 'pam', **kw}, headers=H).get_json()['paper_id']

def test_authors_pass(server, tmp_path, monkeypatch):
    c = server.app.test_client(); conn = server.get_db_connection()
    ten = ' and '.join(f'Name{i}, A.' for i in range(1, 11))
    cut = _add(c, 'Cut comma', 'x', bibkey='cut2001', bibcode='2001C')
    cut2 = _add(c, 'Cut and', 'x', bibkey='cut2002', bibcode='2002C')
    other = _add(c, 'Different people', 'x', bibkey='diff2003', bibcode='2003D')
    gone = _add(c, 'Not on ADS', 'x', bibkey='gone2004', bibcode='2004G')
    bad = _add(c, 'Spatial: H&alpha Images', 'x', bibkey='bad2005', bibcode='2005B')
    soft = _add(c, 'SWarp: Resampling', 'x', bibkey='swarp')
    jour = _add(c, 'Journal', 'Babyk, I.', bibkey='babyk2019', journal='\\pasp')
    grp = _add(c, 'Group', 'Gaia Collaboration and Brown, A. and Magnus Johannesson', bibkey='grp2010')
    upd = lambda pid, a: conn.execute('UPDATE papers SET authors=? WHERE id=?', (a, pid))
    upd(cut, ten.replace(' and Name10, A.', ' and Name10, A., et al.'))
    upd(cut2, ten + ' and et al.'); upd(other, ten + ' and et al.'); upd(gone, ten + ', et al.')
    upd(bad, 'Thompson, R. and Schneider, and Glenn'); upd(soft, 'SWarp: Resampling'); conn.commit()
    sys.path.insert(0, os.path.dirname(server.__file__)); import bibman_repair_accents as R
    monkeypatch.setattr(R, 'DB_PATH', os.environ['DB_PATH'])
    full = [f'Name{i}, A.' for i in range(1, 31)] + ['Euclid Collaboration']
    ads = {'2001C': {'author': full}, '2002C': {'author': full[:12]},
           '2003D': {'author': [f'Other{i}, B.' for i in range(30)]},
           '2005B': {'author': ['Thompson, R.', 'Schneider, Glenn'], 'title': ['Spatial: H$\\alpha$ Images']}}
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
    R.authors_pass(type('A', (), {'out': str(out)}))
    plan = {p['bibkey']: p for p in json.load(open(out / 'authors-plan.json'))['papers']}
    braced = ' and '.join(full[:-1] + ['{Euclid Collaboration}'])     # ADS: a name without a comma is a group
    assert plan['cut2001']['category'] == 'authors' and plan['cut2001']['authors_after'] == braced
    assert plan['grp2010']['category'] == 'groups' and \
        plan['grp2010']['authors_after'] == '{Gaia Collaboration} and Brown, A. and Magnus Johannesson'
    assert 'Magnus Johannesson' in (out / 'authors-report.html').read_text()
    assert plan['cut2002']['category'] == 'authors' and plan['cut2002']['authors_after'] == ' and '.join(full[:12])
    assert plan['diff2003']['category'] == 'check' and 'only 0 of the stored names' in plan['diff2003']['notes'][0]
    assert plan['gone2004']['category'] == 'others' and plan['gone2004']['authors_after'] == ten + ' and others'
    assert plan['bad2005']['category'] == 'check' and plan['bad2005']['title_after'] == 'Spatial: H$\\alpha$ Images'
    assert 'a name with nothing after its comma' in plan['bad2005']['notes']
    assert plan['swarp']['category'] == 'check' and 'the author field repeats the title' in plan['swarp']['notes']
    assert 'babyk2019' not in plan and 'For your decision: 3' in (out / 'authors-report.html').read_text()
    get = lambda pid, f='authors': conn.execute(f'SELECT {f} FROM papers WHERE id=?', (pid,)).fetchone()[0]
    before = {pid: get(pid) for pid in (cut, other, gone, bad)}
    fx = tmp_path / 'fixes.json'
    with open(fx, 'w', encoding='utf-8') as f:
        json.dump({'swarp': {'authors': 'Bertin, E.'}, 'babyk2019': {'journal': 'Advances in Astronomy and Space Physics'}}, f)
    R.apply(type('A', (), {'plan': str(out / 'authors-plan.json'), 'skip': '', 'include': 'bad2005', 'fix': str(fx)}))
    assert get(cut) == braced and get(grp).startswith('{Gaia Collaboration} and') and get(gone) == ten + ' and others' and get(other) == before[other]
    assert get(bad) == 'Thompson, R. and Schneider, Glenn' and get(bad, 'title') == 'Spatial: H$\\alpha$ Images'
    assert get(soft) == 'Bertin, E.' and get(jour, 'journal') == 'Advances in Astronomy and Space Physics'
    R.undo(type('A', (), {'undo': str(sorted(out.glob('undo-*.json'))[-1])}))
    assert get(cut) == before[cut] and get(bad) == before[bad] and get(jour, 'journal') == '\\pasp'
    assert get(bad, 'title') == 'Spatial: H&alpha Images'
