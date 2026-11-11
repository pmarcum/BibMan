"""BibMan tags in the library export for gooTeX's Refs tab (&tags=1, 11 Nov 2026); without it, no change."""
import re
H = {'X-BibMan-Credential': 'test_credential_0123456789'}
ADS = '''@ARTICLE{2020ApJ...900....1S,
       author = {{Smith}, A. and {Jones}, B.},
        title = "{Dust in {AGN} hosts}",
     keywords = {Astrophysics - Astrophysics of Galaxies,
         Galaxies: active},
         year = 2020,
}'''

def setup_library(server):
    c = server.app.test_client()
    post = lambda path, body, user='pam': c.post(path, json={**body, '_username': user}, headers=H).get_json()
    lib = 'ExportTags'
    post('/api/libraries', {'name': lib})
    p1 = post('/api/papers/add-manual', {'title': 'Dust in AGN hosts', 'authors': 'Smith, A.', 'year': '2020', 'bibtex': ADS,
                                         'bibkey': 'smith2020', 'library': lib})['paper_id']
    p2 = post('/api/papers/add-manual', {'title': 'Generated', 'authors': 'Lee, K.', 'year': '2021', 'library': lib})['paper_id']
    p3 = post('/api/papers/add-manual', {'title': 'Untagged', 'authors': 'N, N.', 'year': '2018', 'library': lib,
                                         'bibtex': ADS.replace('Dust in', 'Gas in').replace('2020ApJ...900....1S', 'n'), 'bibkey': 'n2018'})['paper_id']
    L = lambda name, user='pam', private=False: post('/api/tags/labels', {'label': name, 'is_private': private}, user)['id']
    agn, dust, secret, brace, guest = L('xAGN'), L('xdust', 'sarah'), L('xsecret', private=True), L('x{odd}'), L('xTCAN')
    tag = lambda pid, lab, user='pam', **kw: post(f'/api/papers/{pid}/tags', {'label_id': lab, **kw}, user)
    tag(p1, agn); tag(p1, agn, 'sarah'); tag(p1, secret)
    ann = post('/api/annotations', {'paper_id': p1, 'text': 'passage', 'note': 'n'})
    tag(p1, dust, 'sarah', annotation_id=ann.get('id') or ann.get('annotation_id'))      # on a note only
    tag(p2, guest, 'guest-X'); tag(p2, brace)
    return c, lib

def export(c, lib, tags):
    q = f'?library={lib}' + ('&tags=1' if tags else '')
    a = c.get('/api/export/bib-text' + q, headers=H).get_data(as_text=True)
    b = c.get('/get_bib' + q).get_data(as_text=True)
    strip = lambda t: re.sub(r'% Generated: .*', '', t)
    assert strip(a) == strip(b)
    return a

def entry(text, key):
    return text.split('@')[[i for i, e in enumerate(text.split('@')) if e.split(',')[0].endswith('{' + key)][0]]

def test_export_with_and_without_tags(server):
    c, lib = setup_library(server)
    plain, tagged = export(c, lib, False), export(c, lib, True)
    # without &tags=1: stored BibTeX untouched (ADS keywords kept), no BibMan tags anywhere
    assert 'Astrophysics of Galaxies' in plain and 'xAGN' not in plain and 'xTCAN' not in plain
    # with &tags=1: shared labels from anyone (guests too), paper or note level, each once, sorted; never private
    assert 'keywords = {xAGN, xdust},' in entry(tagged, 'smith2020')
    assert 'keywords = {xodd, xTCAN},' in tagged                      # braces left out of the tag name
    assert 'xsecret' not in tagged
    # the stored keywords are replaced, also on a paper without tags
    assert 'Astrophysics of Galaxies' not in tagged
    assert 'keywords' not in entry(tagged, 'n2018')
    assert tagged.count('@') == plain.count('@')
    bibtexparser = __import__('pytest').importorskip('bibtexparser')  # optional: checks the result is valid BibTeX
    db = bibtexparser.loads(tagged)
    assert {e['ID']: e.get('keywords') for e in db.entries}['smith2020'] == 'xAGN, xdust'

def test_keywords_removal_forms(server):
    f = server._bib_set_keywords
    assert f('@article{a, title={T}, KEYWORDS="one, {two}", year={2019}}', None) == '@article{a, title={T}, year={2019}}'
    assert f('@article{a,\n  keywords = {x, {y}},\n  year = 2020\n}', 'Z') == '@article{a,\n  keywords = {Z},\n  year = 2020\n}'
    assert f('@article{a, keywords = bare, year = 1}', None) == '@article{a, year = 1}'
    assert f('@article{a, author_keywords = {keep}, year = 1}', None) == '@article{a, author_keywords = {keep}, year = 1}'
