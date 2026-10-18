"""The demo session is local-only and its token retains nurse permissions."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from patient_memory.auth import synthetic_token
from patient_memory.errors import Problem
from scripts.frontend import LOCAL_JWT_SECRET, PAGE_CSP, SHELL_ROUTES, workspace_app
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


DEPLOYMENT_SECRET = 'deployment-only-test-secret-32-characters'


def hosted_cfg(sandbox):
    return sandbox[0].model_copy(update={'jwt_secret': DEPLOYMENT_SECRET})


def hosted_client(sandbox, cfg=None, **kwargs):
    cfg = cfg or hosted_cfg(sandbox)
    _, patient, actors, _ = sandbox
    app = workspace_app(cfg, actors['nurse'], [
        {'id': str(patient), 'name': 'Synthetic Test', 'reference': 'synthetic-test'}], **kwargs)
    return TestClient(app, base_url='https://demo.example.com', client=('127.0.0.1', 1234))


def test_hosted_mode_allows_only_listed_hosts(sandbox):
    client = hosted_client(sandbox, extra_hosts=('demo.example.com',),
                           demo_token=synthetic_token(sandbox[2]['nurse'], hosted_cfg(sandbox)))
    ok = client.get('/demo/session', headers={'X-PM-Demo': '1',
                                              'Origin': 'https://demo.example.com'})
    assert ok.status_code == 200
    for headers in [{'Host': 'evil.example.com'}, {'Origin': 'https://evil.example.com'},
                    {'Sec-Fetch-Site': 'cross-site'}]:
        assert client.get('/demo/session',
                          headers={'X-PM-Demo': '1', **headers}).status_code == 403
    unlisted = hosted_client(sandbox)
    assert unlisted.get('/demo/session', headers={'X-PM-Demo': '1'}).status_code == 403
    visitor = TestClient(client.app, base_url='https://demo.example.com',
                         client=('192.0.2.10', 1234))
    assert visitor.get('/demo/session', headers={'X-PM-Demo': '1'}).status_code == 200


def test_hosted_mode_serves_configured_demo_token(sandbox):
    _, patient, actors, _ = sandbox
    configured = synthetic_token(actors['nurse'], hosted_cfg(sandbox))
    client = hosted_client(sandbox, extra_hosts=('demo.example.com',), demo_token=configured)
    token = client.get('/demo/session', headers={'X-PM-Demo': '1'}).json()['token']
    assert token == configured
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get(f'/v1/patients/{patient}/timeline').status_code == 200


def test_hosted_mode_requires_a_valid_demo_token(sandbox):
    with pytest.raises(ValueError):
        hosted_client(sandbox, extra_hosts=('demo.example.com',))
    with pytest.raises(Problem):
        hosted_client(sandbox, extra_hosts=('demo.example.com',), demo_token='not.a.jwt')


def test_hosted_mode_refuses_the_public_default_signing_secret(sandbox):
    local = sandbox[0].model_copy(update={'jwt_secret': LOCAL_JWT_SECRET})
    short = sandbox[0].model_copy(update={'jwt_secret': 'short'})
    for cfg in (local, short):
        token = synthetic_token(sandbox[2]['nurse'], cfg)
        with pytest.raises(ValueError, match='deployment-only'):
            hosted_client(sandbox, cfg, extra_hosts=('demo.example.com',), demo_token=token)
    # Loopback-only mode keeps working with the local default.
    assert workspace_client(sandbox).get('/demo/session',
                                         headers={'X-PM-Demo': '1'}).status_code == 200


def test_baseline_pages_share_one_shell_with_mic_csp(sandbox):
    client = workspace_client(sandbox)
    for route in SHELL_ROUTES:
        page = client.get(route.format(patient_id='abc') + '?mode=resident')
        assert page.status_code == 200 and 'baseline.js' in page.text
        assert page.headers['content-security-policy'] == PAGE_CSP
    assert "script-src 'self'" in PAGE_CSP and "media-src 'self' blob:" in PAGE_CSP
    assert client.get('/assets/baseline.js').status_code == 200
    assert 'baseline.js' not in client.get('/').text


def test_shell_health_calls_work_for_the_nurse_token(sandbox):
    """Mirrors the calls in frontend/baseline.js; /v1/health/ready is administrator-only."""
    client = workspace_client(sandbox)
    assert client.get('/v1/health/live').status_code == 200
    token = client.get('/demo/session', headers={'X-PM-Demo': '1'}).json()['token']
    client.headers['Authorization'] = 'Bearer ' + token
    assert client.get(f'/v1/patients/{sandbox[1]}/timeline').status_code == 200
    assert client.get('/v1/health/ready').status_code == 404


def test_check_page_serves_its_scripts_before_the_shell_script(sandbox):
    client = workspace_client(sandbox)
    page = client.get('/check?mode=live&mock=1')
    assert page.status_code == 200
    html = page.text
    assert html.index('check.js') < html.index('baseline.js')
    assert 'check-fixtures.js' not in html  # fixtures load lazily, only for ?mock=1
    for asset in ('check.js', 'check-fixtures.js'):
        assert client.get(f'/assets/{asset}').status_code == 200
