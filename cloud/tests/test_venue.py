"""Conference papers and book chapters (16 Nov 2026): the venue is exported as booktitle in the exports BibTeX reads."""
H = {'X-BibMan-Credential': 'test_credential_0123456789'}

def test_venue_as_booktitle(server):
    c = server.app.test_client(); conn = server.get_db_connection()
    c.post('/api/libraries', json={'name': 'Venue', '_username': 'pam'}, headers=H)
    add = lambda key, ptype, j: c.post('/api/papers/add-manual', json={'title': key, 'authors': 'Doe, J.', 'year': '2021',
          'journal': j, 'pubtype': ptype, 'library': 'Venue', '_username': 'pam', 'bibkey': key}, headers=H).get_json()['paper_id']
    add('conf2021', 'inproceedings', 'American Astronomical Society Meeting Abstracts \\#237')
    add('chap2021', 'incollection', 'Galaxy Evolution Across Time')
    add('art2021', 'article', '\\apj')
    conn.execute("UPDATE papers SET pubtype='inproceedings', bibtex=? WHERE bibkey='conf2021'",
                 ('@inproceedings{conf2021,\n  booktitle = {Old venue},\n  note = {n},\n}',)); conn.commit()
    add('conf2022', 'inproceedings', 'Proceedings of Something')
    comp = c.post('/api/export/bib', json={'bibkeys': ['conf2021', 'chap2021', 'art2021', 'conf2022']}, headers=H).get_json()['bibtex']
    assert 'booktitle = {American Astronomical Society Meeting Abstracts \\#237}' in comp and 'Old venue' not in comp
    assert 'booktitle = {Galaxy Evolution Across Time}' in comp and 'booktitle = {Proceedings of Something}' in comp
    assert 'journal = {\\apj}' in comp and comp.count('journal =') == 1          # articles unchanged
    drive = c.get('/get_bib?library=Venue&latex=1').get_data(as_text=True)
    assert 'booktitle = {Galaxy Evolution Across Time}' in drive
    refs = c.get('/get_bib?library=Venue&tags=1').get_data(as_text=True)
    chap = refs.split('@incollection{chap2021,')[1].split('\n}')[0]
    assert 'journal = {Galaxy Evolution Across Time}' in chap and 'booktitle' not in chap   # Refs tab: as stored

def test_booktitle_read_into_journal(server):
    c = server.app.test_client(); conn = server.get_db_connection()
    bib = '@inproceedings{x,\n  author = {Roe, R.},\n  title = {A talk},\n  booktitle = {SPIE Conference Series},\n  year = 2020,\n}'
    c.post('/api/papers/import-bib', json={'bib_content': bib, 'library': 'Extragalactic'}, headers=H)
    r = conn.execute("SELECT id, journal FROM papers WHERE title='A talk'").fetchone()
    assert r['journal'] == 'SPIE Conference Series'
    c.put(f"/api/papers/{r['id']}/bibtex", json={'bibtex': bib.replace('SPIE Conference Series', 'SPIE 11443')}, headers=H)
    assert conn.execute('SELECT journal FROM papers WHERE id=?', (r['id'],)).fetchone()[0] == 'SPIE 11443'
