"""Shared set-up for the server's tests: a fresh database in a temporary folder, and no contact with GitHub.

    cd cloud && ../venv/bin/python -m pytest tests -q        (or any Python with the server's requirements and pytest)
"""
import importlib.util, os, subprocess, sys, tempfile
from pathlib import Path
import pytest

CLOUD = Path(__file__).resolve().parent.parent

@pytest.fixture(scope='session')
def server():
    """The server module, loaded once against a new, empty database."""
    tmp = tempfile.mkdtemp(prefix='bibman_test_')
    db = os.path.join(tmp, 'bibman.db')
    subprocess.run([sys.executable, str(CLOUD / 'init_db.py')], check=True, capture_output=True, cwd=str(CLOUD),
                   env={**os.environ, 'DB_PATH': db, 'LIBRARY_NAME': 'Extragalactic'})
    os.environ.update(DB_PATH=db, GAS_CREDENTIAL='test_credential_0123456789', SESSION_SECRET='test')
    spec = importlib.util.spec_from_file_location('bibman_server_under_test', CLOUD / 'bibman_e2micro_server.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

@pytest.fixture(autouse=True)
def no_github(monkeypatch, request):
    """Tests never contact GitHub: any real request from the server's GitHub helper fails the test."""
    if 'server' not in request.fixturenames:
        return
    srv = request.getfixturevalue('server')
    def refuse(*args, **kwargs):
        raise AssertionError('a test tried to contact GitHub')
    monkeypatch.setattr(srv.requests, 'request', refuse)
