from uuid import uuid4

from patient_memory.auth import synthetic_token
from tests.contract.test_frontend import workspace_client


def test_cross_device_room_authorization_and_no_patient_history_writes(sandbox):
    cfg, _, actors, _ = sandbox
    nurse = workspace_client(sandbox)
    assert nurse.post('/demo/handoff', json={}).status_code == 401
    assert nurse.post('/demo/handoff', json={}, headers={
        'Authorization': 'Bearer ' + synthetic_token(actors['psw'], cfg)}).status_code == 404
    auth = {'Authorization': 'Bearer ' + synthetic_token(actors['nurse'], cfg)}
    response = nurse.post('/demo/handoff', json={}, headers=auth)
    assert response.status_code == 201
    room = response.json()
    base = '/demo/handoff/' + room['room']
    def headers(role):
        return {'Authorization': 'Bearer ' + room['keys'][role]}
    assert nurse.get(base, headers=headers('runner')).status_code == 404
    assert nurse.post(base + '/context', json={'tag': 'exertion'},
                      headers=headers('runner')).status_code == 404
    body = {'request_id': str(uuid4()), 'duration_s': 20}
    receipt = nurse.post(base + '/checks', json=body, headers=headers('runner'))
    assert receipt.json() == {'id': body['request_id'], 'accepted': True, 'remaining_checks': 0}
    assert nurse.post(base + '/checks', json=body, headers=headers('runner')).json() == receipt.json()
    assert nurse.post(base + '/checks', json={**body, 'verdict': 'escalate'},
                      headers=headers('resident')).status_code == 422
    explained = nurse.post(base + '/context', json={'tag': 'exertion'}, headers=headers('nurse'))
    assert explained.json()['checks'][0]['verdict'] == 'explained'
    # Capabilities cannot be used as ordinary API identities.
    assert nurse.get('/v1/watchlist', headers=headers('nurse')).status_code == 401
    assert nurse.delete(base, headers=headers('runner')).status_code == 404
    assert nurse.delete(base, headers=headers('nurse')).status_code == 200
    assert nurse.post(base + '/checks', json=body, headers=headers('runner')).status_code == 404


def test_handoff_inherits_origin_json_and_host_guards(sandbox):
    client = workspace_client(sandbox)
    auth = {'Authorization': 'Bearer ' + synthetic_token(sandbox[2]['nurse'], sandbox[0])}
    assert client.post('/demo/handoff', json={}, headers={**auth,
        'Origin': 'https://untrusted.example'}).status_code == 403
    assert client.post('/demo/handoff', content=b'audio', headers={**auth,
        'Content-Type': 'audio/webm'}).status_code == 415
    assert client.get('/assets/demo-handoff.js').status_code == 200
