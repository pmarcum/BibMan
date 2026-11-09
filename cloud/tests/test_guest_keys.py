"""Guest bookmarklets' keys (9 Nov 2026): create, list, change the end date, End now, and the check the bookmarklet
web app makes on every click."""
import pytest

H = {'X-BibMan-Credential': 'test_credential_0123456789'}

@pytest.fixture
def api(server):
    server.get_db_connection().execute('DELETE FROM guest_keys').connection.commit()
    c = server.app.test_client()
    def call(method, path, body=None, user='pam'):
        body = {**(body or {}), '_username': user} if method == 'POST' else None
        r = c.open(path, method=method, json=body, headers=H)
        return r.status_code, r.get_json()
    call.today = server._guest_today
    return call

def later(server_today, days):
    from datetime import date, timedelta
    return (date.fromisoformat(server_today()) + timedelta(days=days)).isoformat()

def create(api, project='TCAN26', ends=None, library='Extragalactic', user='pam'):
    return api('POST', '/api/guest-keys', {'project': project, 'library': library, 'ends_on': ends or later(api.today, 90)}, user)

def test_needs_the_credential(server):
    assert server.app.test_client().get('/api/guest-keys').status_code == 401
    assert server.app.test_client().get('/api/guest-keys/check?key=x').status_code == 401

def test_create_and_check(api):
    code, j = create(api)
    k = j['key']
    assert code == 200 and j['existing'] is False and k['state'] == 'active' and k['library'] == 'Extragalactic'
    assert k['created_by'] == 'pam' and k['guest_name'] == 'guest-TCAN26' and len(k['key']) >= 32
    code, c = api('GET', '/api/guest-keys/check?key=' + k['key'])
    assert c['ok'] is True and c['library'] == 'Extragalactic' and c['guest_name'] == 'guest-TCAN26' and c['created_by'] == 'pam'
    assert api('GET', '/api/guest-keys/check?key=wrong')[1] == {'ok': False, 'reason': 'unknown'}
    assert api('GET', '/api/guest-keys/check?key=')[1] == {'ok': False, 'reason': 'unknown'}

def test_one_key_per_project_case_ignored(api):
    first = create(api)[1]['key']
    code, j = create(api, project='tcan26', user='sarah')
    assert j['existing'] is True and j['key']['id'] == first['id'] and j['key']['created_by'] == 'pam'
    assert len(api('GET', '/api/guest-keys')[1]['keys']) == 1

def test_rules(api):
    assert create(api, project='  ')[0] == 400
    assert create(api, project='x' * 41)[0] == 400
    assert create(api, project='x' * 40)[0] == 200
    assert create(api, project='P2', ends=later(api.today, -1))[0] == 400          # yesterday
    assert create(api, project='P3', ends='2027-02-30')[0] == 400                  # not a date
    assert create(api, project='P4', ends=api.today())[0] == 200                   # today is fine
    assert create(api, project='P5', library='Nope')[0] == 404

def test_past_date_then_reopen(api, server):
    k = create(api)[1]['key']
    conn = server.get_db_connection()
    conn.execute('UPDATE guest_keys SET ends_on=? WHERE id=?', (later(api.today, -1), k['id'])); conn.commit(); conn.close()
    c = api('GET', '/api/guest-keys/check?key=' + k['key'])[1]
    assert c['ok'] is False and c['reason'] == 'past_date' and c['created_by'] == 'pam'
    assert create(api)[1]['existing'] is True                                     # still the project's key
    assert api('POST', f'/api/guest-keys/{k["id"]}/ends-on', {'ends_on': later(api.today, -1)})[0] == 400
    code, j = api('POST', f'/api/guest-keys/{k["id"]}/ends-on', {'ends_on': later(api.today, 30)})
    assert code == 200 and j['key']['state'] == 'active'
    assert api('GET', '/api/guest-keys/check?key=' + k['key'])[1]['ok'] is True     # same link works again

def test_end_now_is_final(api):
    k = create(api)[1]['key']
    code, j = api('POST', f'/api/guest-keys/{k["id"]}/end-now', user='sarah')
    assert code == 200 and j['key']['state'] == 'ended' and j['key']['ended_now_by'] == 'sarah'
    c = api('GET', '/api/guest-keys/check?key=' + k['key'])[1]
    assert c['ok'] is False and c['reason'] == 'ended' and c['ended_now_by'] == 'sarah'
    assert api('POST', f'/api/guest-keys/{k["id"]}/ends-on', {'ends_on': later(api.today, 30)})[0] == 400
    code, j = create(api)                                                          # a new key for the project
    assert j['existing'] is False and j['key']['id'] != k['id'] and j['key']['key'] != k['key']
    keys = api('GET', '/api/guest-keys')[1]['keys']
    assert [x['state'] for x in keys] == ['active', 'ended']                       # ended ones stay, listed last

def test_list_order_and_count(api, server):
    a = create(api, project='A')[1]['key']; b = create(api, project='B')[1]['key']; c = create(api, project='C')[1]['key']
    api('POST', f'/api/guest-keys/{a["id"]}/end-now')
    conn = server.get_db_connection()
    conn.execute('UPDATE guest_keys SET ends_on=? WHERE id=?', (later(api.today, -3), b['id'])); conn.commit(); conn.close()
    api('POST', f'/api/guest-keys/{c["id"]}/added'); api('POST', f'/api/guest-keys/{c["id"]}/added')
    j = api('GET', '/api/guest-keys')[1]
    assert [(k['project'], k['state']) for k in j['keys']] == [('C', 'active'), ('B', 'past_date'), ('A', 'ended')]
    assert j['keys'][0]['papers_added'] == 2 and j['project_max'] == 40 and j['today'] == api.today()

def test_library_gone(api, server):
    k = create(api)[1]['key']
    conn = server.get_db_connection()
    conn.execute("UPDATE guest_keys SET library_id='gone' WHERE id=?", (k['id'],)); conn.commit(); conn.close()
    c = api('GET', '/api/guest-keys/check?key=' + k['key'])[1]
    assert c['ok'] is False and c['reason'] == 'no_library'

def test_schema_file_has_the_table(server):
    from pathlib import Path
    assert 'CREATE TABLE guest_keys' in (Path(server.__file__).parent / 'schema.sql').read_text()

def test_made_on_an_existing_database(server):
    """The VM's database predates the table: the server makes it on its next connection."""
    conn = server.get_db_connection(); conn.execute('DROP TABLE guest_keys'); conn.commit(); conn.close()
    conn = server.get_db_connection()
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='guest_keys'").fetchone()
    conn.close()
