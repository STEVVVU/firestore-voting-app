from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

import app
from google.api_core.exceptions import Aborted, DeadlineExceeded, RetryError, ServiceUnavailable


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("VOTING_BACKEND", "sqlite")
    monkeypatch.setenv("IDENTITY_MODE", "local")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "votes.sqlite3"))
    with TestClient(app.app) as client:
        yield client


def test_vote_auth_validation_and_idempotence(client):
    assert client.post('/votes', json={'team': 'TABS'}).status_code == 401
    headers = {'Authorization': 'Bearer local:alice'}
    assert client.post('/votes', json={'team': 'OTHER'}, headers=headers).status_code == 422
    assert client.post('/votes', json={'team': 'TABS'}, headers=headers).status_code == 200
    assert client.post('/votes', json={'team': 'TABS'}, headers=headers).status_code == 200
    assert client.post('/votes', json={'team': 'SPACES'}, headers=headers).status_code == 409
    data = client.get('/results').json()
    assert data['counts'] == {'TABS': 1, 'SPACES': 0}
    assert set(data['recent'][0]) == {'team', 'cast_at'}
    assert 'alice' not in str(data)


def test_concurrent_duplicate_and_distinct_voters(client):
    def cast(i):
        return client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': f'Bearer local:{i}'}).status_code
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert all(code == 200 for code in pool.map(cast, [0] * 20 + list(range(1, 21))))
    assert client.get('/results').json()['counts']['TABS'] == 21


def test_production_rejects_local_adapters(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('VOTING_BACKEND', 'sqlite')
    monkeypatch.setenv('IDENTITY_MODE', 'local')
    with pytest.raises(RuntimeError):
        app.settings()


def test_firebase_verification_boundary(client, monkeypatch):
    client.app.state.identity = 'firebase'
    calls = []
    monkeypatch.setattr(app.auth, 'verify_id_token', lambda token, check_revoked: calls.append((token, check_revoked)) or {'uid': 'verified'})
    assert client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': 'Bearer signed-token'}).status_code == 200
    assert calls == [('signed-token', True)]
    def reject(*args, **kwargs):
        raise ValueError('invalid')
    monkeypatch.setattr(app.auth, 'verify_id_token', reject)
    assert client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': 'Bearer bad'}).status_code == 401


def test_verifier_failure_closed_and_no_write(client, monkeypatch):
    client.app.state.identity = 'firebase'
    def unavailable(*args, **kwargs):
        raise OSError('network failure')
    monkeypatch.setattr(app.auth, 'verify_id_token', unavailable)
    response = client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': 'Bearer untrusted'})
    assert response.status_code == 503
    assert client.get('/results').json()['counts'] == {'TABS': 0, 'SPACES': 0}


@pytest.mark.parametrize(('error', 'status'), [
    (app.auth.RevokedIdTokenError('revoked'), 401),
    (app.auth.ExpiredIdTokenError('expired', None), 401),
    (app.auth.UserDisabledError('disabled'), 401),
    (app.auth.CertificateFetchError('unavailable', None), 503),
])
def test_firebase_auth_rejections(client, monkeypatch, error, status):
    client.app.state.identity = 'firebase'
    def reject(*args, **kwargs):
        raise error
    monkeypatch.setattr(app.auth, 'verify_id_token', reject)
    response = client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': 'Bearer untrusted'})
    assert response.status_code == status
    assert client.get('/results').json()['counts'] == {'TABS': 0, 'SPACES': 0}


@pytest.mark.parametrize('setting', ['FIREBASE_AUTH_EMULATOR_HOST', 'FIRESTORE_EMULATOR_HOST'])
def test_production_rejects_emulator(monkeypatch, setting):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('VOTING_BACKEND', 'firestore')
    monkeypatch.setenv('IDENTITY_MODE', 'firebase')
    monkeypatch.setenv(setting, '127.0.0.1:18880')
    with pytest.raises(RuntimeError, match='Emulators'):
        app.settings()


def test_production_requires_configuration(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.setenv('VOTING_BACKEND', 'firestore')
    monkeypatch.setenv('IDENTITY_MODE', 'firebase')
    monkeypatch.delenv('GOOGLE_CLOUD_PROJECT', raising=False)
    with pytest.raises(RuntimeError, match='GOOGLE_CLOUD_PROJECT'):
        app.settings()


@pytest.mark.parametrize('error', [Aborted('contention'), DeadlineExceeded('timeout'), ServiceUnavailable('unavailable'), RetryError('exhausted', cause=TimeoutError())])
def test_storage_failures_are_retryable(client, monkeypatch, error):
    def fail(*args):
        raise error
    monkeypatch.setattr(client.app.state.store, 'cast', fail)
    response = client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': 'Bearer local:alice'})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Vote storage unavailable; retry the same choice'


def test_result_storage_timeout_is_retryable(client, monkeypatch):
    def fail():
        raise DeadlineExceeded('timeout')
    monkeypatch.setattr(client.app.state.store, 'results', fail)
    response = client.get('/results')
    assert response.status_code == 503
    assert response.json()['detail'] == 'Results unavailable; retry later'
