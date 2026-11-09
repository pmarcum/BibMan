"""The "about" answer behind the dashboard's version line (8 Nov 2026), with stand-in GitHub answers."""
import time
import pytest

PAGE   = {'sha': 'p' * 40, 'commit': {'committer': {'date': '2026-11-08T21:56:00Z'}}}
SERVER = {'sha': 's' * 40, 'commit': {'committer': {'date': '2026-11-08T22:15:00Z'}}}
def older(i): return {'sha': f'{i}' * 40, 'commit': {'committer': {'date': f'2026-10-{10 + i:02d}T12:00:00Z'}}}
HISTORY = [SERVER] + [older(i) for i in range(1, 10)]          # main's last 10 server versions, newest first

class Answer:
    def __init__(self, status=200, json=None):
        self.status_code, self._json = status, json
    @property
    def ok(self): return self.status_code < 400
    def json(self): return self._json
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(f'HTTP {self.status_code}')

def github(server, folder_blob, blob_known=True, fail=False, blobs=None):
    """A stand-in for GitHub: records every request. folder_blob is the server file's hash in main; blobs maps an older
    commit to the server file's hash at that commit (any other older commit has some other file)."""
    calls, blobs = [], blobs or {}
    def fake(method, path, params=None):
        calls.append((method, path, (params or {}).get('ref')))
        if fail: raise ConnectionError('GitHub unreachable')
        if path == 'commits':
            return Answer(json=[PAGE] if params['path'] == 'Index.html' else HISTORY[:params['per_page']])
        if path == 'contents/cloud':
            ref = (params or {}).get('ref')
            blob = folder_blob if ref is None else blobs.get(ref, 'o' * 40)
            return Answer(json=[{'name': 'init_db.py', 'sha': 'x' * 40}, {'name': 'bibman_e2micro_server.py', 'sha': blob}])
        if path.startswith('git/blobs/'):
            return Answer(200 if blob_known else 404)
        raise AssertionError(path)
    return fake, calls

@pytest.fixture
def fresh(server, monkeypatch):
    """Start every test with an empty cache."""
    monkeypatch.setitem(server._ABOUT, 'value', None)
    monkeypatch.setitem(server._ABOUT, 'at', 0.0)
    monkeypatch.setitem(server._ABOUT, 'refreshing', False)
    monkeypatch.setitem(server._HISTORY, 'key', None)
    monkeypatch.setitem(server._HISTORY, 'value', None)
    server._ABOUT_READY.clear()
    return server

def test_blob_hash_matches_git(server):
    assert server.git_blob_sha(b'hello\n') == 'ce013625030ba8dba906f756967f9e9ca394464a'   # `git hash-object` of "hello\n"

def test_up_to_date(fresh, monkeypatch):
    fake, calls = github(fresh, fresh.RUNNING_SERVER_BLOB)
    monkeypatch.setattr(fresh, '_github', fake)
    a = fresh.compute_about()
    assert a['server_update'] is False and a['server_on_github'] is True
    assert a['server']['commit'] == 's' * 40 and a['server']['date'] == '2026-11-08T22:15:00Z'
    assert a['page'] == {'commit': 'p' * 40, 'date': '2026-11-08T21:56:00Z'}
    assert a['server_in_main'] is True
    assert not any(p.startswith('git/blobs/') or r for _, p, r in calls)   # no extra questions when the hashes match

def test_update_waiting(fresh, monkeypatch):
    fake, calls = github(fresh, 'n' * 40, blobs={'3' * 40: fresh.RUNNING_SERVER_BLOB})   # we run main's version from 3 changes back
    monkeypatch.setattr(fresh, '_github', fake)
    a = fresh.compute_about()
    assert a['server_update'] is True and a['server_on_github'] is True and a['server_in_main'] is True
    assert a['server_latest']['commit'] == 's' * 40
    assert a['server']['commit'] == '3' * 40 and a['server']['date'] == '2026-10-13T12:00:00Z'
    assert [r for _, p, r in calls if p == 'contents/cloud' and r] == ['1' * 40, '2' * 40, '3' * 40]   # stops when found
    assert not any(p.startswith('git/blobs/') for _, p, _ in calls)

def test_on_a_test_branch_is_not_an_update(fresh, monkeypatch):
    """8 Nov 2026: the new server was on GitHub (pushed to ui-test) but not in main; it must not be called older."""
    fake, calls = github(fresh, 'n' * 40, blob_known=True)
    monkeypatch.setattr(fresh, '_github', fake)
    a = fresh.compute_about()
    assert a['server_update'] is None and a['server_on_github'] is True and a['server_in_main'] is False
    assert 'commit' not in a['server']
    assert len([1 for _, p, r in calls if p == 'contents/cloud' and r]) == fresh.ABOUT_HISTORY_DEPTH - 1   # all 9 older ones
    assert ('HEAD', 'git/blobs/' + fresh.RUNNING_SERVER_BLOB, None) in calls

def test_running_version_not_on_github(fresh, monkeypatch):
    fake, _ = github(fresh, 'n' * 40, blob_known=False)
    monkeypatch.setattr(fresh, '_github', fake)
    a = fresh.compute_about()
    assert a['server_update'] is None and a['server_on_github'] is False and a['server_in_main'] is False
    assert a['server']['fingerprint'] == fresh.RUNNING_SERVER_BLOB[:12]

def test_history_looked_at_once_per_main_change(fresh, monkeypatch):
    fake, calls = github(fresh, 'n' * 40, blob_known=True)
    monkeypatch.setattr(fresh, '_github', fake)
    fresh.compute_about(); first = len(calls)
    fresh.compute_about()
    assert len(calls) - first == 3          # the next check: Index.html, the server's history, main's folder listing
    HISTORY[0] = {'sha': 'm' * 40, 'commit': {'committer': {'date': '2026-11-09T08:00:00Z'}}}
    try:
        before = len(calls); fresh.compute_about()
        assert len(calls) - before > 3      # main changed: looked back again
    finally:
        HISTORY[0] = SERVER

def test_github_unreachable(fresh, monkeypatch):
    fake, _ = github(fresh, '', fail=True)
    monkeypatch.setattr(fresh, '_github', fake)
    a = fresh.compute_about()
    assert a == {'server': {'fingerprint': fresh.RUNNING_SERVER_BLOB[:12]}, 'page': None, 'server_update': None,
                 'server_on_github': None, 'server_in_main': None, 'server_latest': None}

def test_asked_at_most_every_10_minutes(fresh, monkeypatch):
    fake, calls = github(fresh, '', fail=True)                 # failures are kept just as long as answers
    monkeypatch.setattr(fresh, '_github', fake)
    first = fresh.get_about()
    for _ in range(5): assert fresh.get_about() == first
    assert len(calls) == 1
    monkeypatch.setitem(fresh._ABOUT, 'at', time.time() - fresh.ABOUT_CACHE_SECONDS - 1)   # 10 minutes later
    fresh.get_about(); time.sleep(0.3)
    assert len(calls) == 2

def test_field_in_startup_response(fresh, monkeypatch):
    fake, _ = github(fresh, fresh.RUNNING_SERVER_BLOB)
    monkeypatch.setattr(fresh, '_github', fake)
    r = fresh.app.test_client().get('/api/libraries/current', headers={'X-BibMan-Credential': 'test_credential_0123456789'})
    j = r.get_json()
    assert r.status_code == 200 and j['library_name'] == 'Extragalactic' and j['library_id']
    assert j['about']['server_update'] is False and j['about']['page']['commit'] == 'p' * 40

def test_real_github_helper_is_blocked(server):
    with pytest.raises(AssertionError, match='contact GitHub'):
        server._github('GET', 'commits')
