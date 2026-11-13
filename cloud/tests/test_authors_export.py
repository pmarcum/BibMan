"""Author lists, LaTeX's own characters and stored entries in the exports (13 Nov 2026)."""
H = {'X-BibMan-Credential': 'test_credential_0123456789'}

def _add(c, title, authors, lib='Extragalactic', **kw):
    return c.post('/api/papers/add-manual', json={'title': title, 'authors': authors, 'year': '2020', 'library': lib,
                                                  '_username': 'pam', **kw}, headers=H).get_json()

def test_author_rules(server):
    a = server._bib_authors
    many = ' and '.join(f'Name{i}, A.' for i in range(20))
    assert a(many, True) == ' and '.join(f'Name{i}, A.' for i in range(15)) + ' and others'
    assert a(many, False) == many                                       # Refs tab: as stored
    fifteen = ' and '.join(f'Name{i}, A.' for i in range(15))
    assert a(fifteen, True) == fifteen                                  # 15 names: no "others"
    assert a('Hartley, J. and Holder, Bradley, et al.', True) == 'Hartley, J. and Holder, Bradley and others'
    assert a('Hartley, J. and Holder, B. and et al.', True) == 'Hartley, J. and Holder, B. and others'
    assert a('Hartley, J. and others', True) == 'Hartley, J. and others'
    assert a('{Gaia Collaboration} and Brown, A. G. A.', True) == '{Gaia Collaboration} and Brown, A. G. A.'
    assert a('Gaia Collaboration and Magnus Johannesson', True) == 'Gaia Collaboration and Magnus Johannesson'  # never braced here
    assert a('{National Academies of Sciences, Engineering, and Medicine}', True) == \
        '{National Academies of Sciences, Engineering, and Medicine}'   # already one name: split nowhere
    assert a('Sodré, L., Jr. and Werle, A.', True) == 'Sodré, Jr., L. and Werle, A.'
    assert a('Plato and Smith, J.', True) == 'Plato and Smith, J.'

def test_names_keep_whole_name_braces(server):
    n = server.names_from_latex
    assert n(r'{National Academies of Sciences, Engineering, and Medicine}') == \
        '{National Academies of Sciences, Engineering, and Medicine}'
    assert n(r"{Gaia Collaboration} and {Rom{\'a}n}, Javier") == '{Gaia Collaboration} and Román, Javier'
    assert n(r"{Rom{\'a}n}, Javier and Mart{\'\i}n, R.") == 'Román, Javier and Martín, R.'   # as before

def test_latex_specials(server):
    v = server._latex_value
    assert v('Chandra & CIAO #1 at 80% \\& 5\\%') == r'Chandra \& CIAO \#1 at 80\% \& 5\%'
    assert v(r'see \url{https://x.org/a%20b#c&d} & more') == r'see \url{https://x.org/a%20b#c&d} \& more'
    e = '@misc{k,\n  title = {{A & B}},\n  url = {https://x.org/?a=1&b=2#c},\n}'
    out = server.latex_ascii_entry(e)
    assert r'{{A \& B}}' in out and 'https://x.org/?a=1&b=2#c' in out

def test_stored_entry_takes_fields(server):
    c = server.app.test_client(); conn = server.get_db_connection()
    c.post('/api/libraries', json={'name': 'Stored', '_username': 'pam'}, headers=H)
    p = _add(c, 'Spatial Distribution: H$\\alpha$ Images', 'García-Barreto, J. A. and Escalante-Ramírez, B.',
             lib='Stored', bibkey='gb1996', journal='\\rmxaa')
    damaged = ('@article{oldkey,\n  author = {Garc{\\\'\\i}a-Barreto, J.~A. and Escalante-Ram\\\'rez, B.},\n'
               '  title = {Spatial Distribution: H&alpha Images},\n  journal = {Revista Mexicana},\n'
               '  note = {kept as it is},\n  year = 1996,\n}')
    conn.execute('UPDATE papers SET bibtex=? WHERE id=?', (damaged, p['paper_id'])); conn.commit()
    comp = c.post('/api/export/bib', json={'bibkeys': ['gb1996']}, headers=H).get_json()['bibtex']
    assert comp.startswith('@article{gb1996,')                          # the key cited, not the stored one
    assert "Escalante-Ram{\\'\\i}rez" in comp and 'H$\\alpha$' in comp and '&alpha' not in comp
    assert 'journal = {\\rmxaa}' in comp and 'note = {kept as it is}' in comp and 'year = {2020}' in comp
    refs = c.get('/get_bib?library=Stored&tags=1').get_data(as_text=True)
    assert 'Escalante-Ramírez' in refs and 'note = {kept as it is}' in refs
    shown = c.get(f"/api/papers/{p['paper_id']}", headers=H).get_json()['bibtex']
    assert 'Escalante-Ramírez' in shown and 'note = {kept as it is}' in shown

def test_edit_bibtex_updates_fields(server):
    c = server.app.test_client(); conn = server.get_db_connection()
    p = _add(c, 'Old title', 'Doe, J.', bibkey='doe2020edit')
    typed = ('@article{doe2020edit,\n  author = {{Euclid Collaboration} and Borlaff, A. S. and Sodr{\\\'e}, L., Jr.},\n'
             '  title = "{New title at z $\\sim$ 2}",\n  journal = {\\aap},\n  year = 2022,\n  note = {x},\n}')
    c.put(f"/api/papers/{p['paper_id']}/bibtex", json={'bibtex': typed}, headers=H)
    r = conn.execute('SELECT authors, title, journal, year, bibtex FROM papers WHERE id=?', (p['paper_id'],)).fetchone()
    assert r['authors'] == '{Euclid Collaboration} and Borlaff, A. S. and Sodré, L., Jr.'
    assert r['title'] == 'New title at z $\\sim$ 2' and r['journal'] == '\\aap' and str(r['year']) == '2022'
    comp = c.post('/api/export/bib', json={'bibkeys': ['doe2020edit']}, headers=H).get_json()['bibtex']
    assert "{Euclid Collaboration} and Borlaff, A. S. and Sodr{\\'e}, Jr., L." in comp and 'note = {x}' in comp
