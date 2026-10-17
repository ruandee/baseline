"""The demo session is local-only and its token retains nurse permissions."""
from uuid import uuid4

from fastapi.testclient import TestClient

from scripts.frontend import workspace_app
from tests.contract.test_api import import_note, source_payload


def workspace_client(sandbox):
    cfg, patient, actors, _ = sandbox
    app = workspace_app(cfg, actors['nurse'], [
        {'id': str(patient), 'name': 'Synthetic Test', 'reference': 'synthetic-test'}])
    return TestClient(app, base_url='http://127.0.0.1:8001', client=('127.0.0.1', 1234))


def test_workspace_local_session_and_read_scope(sandbox):
    import_note(sandbox)
    client = workspace_client(sandbox)
    session = client.get('/demo/session', headers={'X-PM-Demo': '1'})
    assert session.status_code == 200
    assert session.headers['cache-control'] == 'no-store'
    token = session.json()['token']
    client.headers['Authorization'] = 'Bearer ' + token
    root = f'/v1/patients/{sandbox[1]}'
    assert client.get(root + '/timeline').json()['events']
    assert client.post(root + '/questions', json={'question': 'sleep'}).status_code == 200
    assert client.get(f'/v1/patients/{uuid4()}/timeline').status_code == 404
    assert client.post(root + '/sources', json=source_payload(),
                       headers={'Idempotency-Key': 'frontend-denied'}).status_code == 404
    assert client.get('/').status_code == 200
    assert client.get('/assets/app.js').status_code == 200


def test_workspace_rejects_cross_origin_and_remote_bootstrap(sandbox):
    client = workspace_client(sandbox)
    assert client.get('/demo/session').status_code == 403
    for headers in [
        {'Origin': 'https://example.com'}, {'Host': 'rebound.example.com'},
        {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'http://127.0.0.1:9000'},
    ]:
        assert client.get('/demo/session', headers={'X-PM-Demo': '1', **headers}).status_code == 403
    remote = TestClient(client.app, base_url='http://127.0.0.1:8001',
                        client=('192.0.2.10', 1234))
    assert remote.get('/demo/session', headers={'X-PM-Demo': '1'}).status_code == 403
