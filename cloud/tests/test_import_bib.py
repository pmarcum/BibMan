"""Import .bib reads entries brace by brace (12 Nov 2026): ADS's own BibTeX (title = "{...}", year = 2011, braces
nested three deep) is read whole, and simple entries are read exactly as before."""
import re
H = {'X-BibMan-Credential': 'test_credential_0123456789'}

def _old_fields(fields_str):          # the reader before 12 Nov 2026, kept here to show simple entries read the same
    return {m.group(1).lower(): m.group(2).strip()
            for m in re.finditer(r'(\w+)\s*=\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', fields_str, re.DOTALL)}

ADS = r'''@ARTICLE{2011MNRAS.412..684B,
       author = {{Bernardi}, M. and {Roche}, N. and {Shankar}, F. and {Sheth}, R.~K.},
        title = "{Curvature in the colour-magnitude relation but not in colour-{\ensuremath{\sigma}}: major dry mergers at M$_{*}$ {\ensuremath{>}} 2 {\texttimes} {}10$^{11}$ M$_{\ensuremath{\odot}}$?}",
      journal = {\mnras},
         year = 2011,
        month = feb,
       volume = {412},
        pages = {684-704},
          doi = {10.1111/j.1365-2966.2010.17950.x},
       adsurl = {https://ui.adsabs.harvard.edu/abs/2011MNRAS.412..684B},
      adsnote = {Provided by the SAO/NASA Astrophysics Data System}
}
@comment{jabref-meta: databaseType:bibtex;}
@article{smith2020,
  author = {Smith, J. and M{\"u}ller, O.},
  title = {A {HST} view of z $\sim$ 2},
  journal = {ApJ}, year = {2020}, volume = {900}, pages = {1},
  note = {contact: someone@example.org}
}
'''

def test_simple_entries_read_as_before(server):
    simple = ['\n  author = {Smith, J. and M{\\"u}ller, O.},\n  title = {A {HST} view of z $\\sim$ 2},\n  year = {2020},\n',
              '\n author={Doe, A.}, title={Plain}, journal={AJ}, volume={1}, pages={2-3}, doi={10.1/x}\n']
    for f in simple:
        assert server._bib_fields(f) == _old_fields(f)

def test_ads_entry_read_whole(server):
    entries = server._bib_entries(ADS)
    assert [(t, k) for t, k, _ in entries] == [('ARTICLE', '2011MNRAS.412..684B'), ('article', 'smith2020')]
    f = server._bib_fields(entries[0][2])
    assert f['year'] == '2011' and f['month'] == 'feb' and f['volume'] == '412'      # bare values, once missed
    assert f['title'].startswith(r'Curvature in the colour-magnitude relation but not in colour-{\ensuremath{\sigma}}')
    assert f['title'].endswith(r'M$_{\ensuremath{\odot}}$?')                         # outer "{...}" removed
    assert server._bib_fields(entries[1][2])['note'] == 'contact: someone@example.org'  # an @ inside a value

def test_import_route(server):
    c = server.app.test_client(); conn = server.get_db_connection()
    r = c.post('/api/papers/import-bib', json={'bib_content': ADS, 'library': 'Extragalactic'}, headers=H).get_json()
    assert r['added'] == 2
    p = conn.execute("SELECT * FROM papers WHERE doi='10.1111/j.1365-2966.2010.17950.x'").fetchone()
    assert p['bibkey'].startswith('bernardi+2011') and str(p['year']) == '2011'
    assert p['authors'] == 'Bernardi, M. and Roche, N. and Shankar, F. and Sheth, R. K.'
    assert r'{\ensuremath{\sigma}}' in p['title'] and p['bibtex'].count('adsnote') == 1
    s = conn.execute("SELECT * FROM papers WHERE title LIKE 'A {HST} view%'").fetchone()
    assert s['authors'] == 'Smith, J. and Müller, O.' and str(s['year']) == '2020' and s['journal'] == 'ApJ'
