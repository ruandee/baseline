from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from scripts.demo_handoff import Explanation, Rooms, Submission


def submission(**kwargs):
    return Submission(request_id=uuid4(), duration_s=20, **kwargs)


def test_two_residents_progress_independently_and_context_does_not_rewrite_receipts():
    rooms = Rooms()
    room = rooms.create()
    rid, keys = room['room'], room['keys']
    runner, first, second = submission(), submission(), submission()
    rooms.submit(rid, keys['runner'], runner)
    before = rooms.snapshot(rid, keys['nurse'])
    assert before['checks'][0]['verdict'] == 'watch'
    rooms.explain(rid, keys['nurse'])
    rooms.submit(rid, keys['resident'], first)
    rooms.submit(rid, keys['resident'], second)
    result = rooms.snapshot(rid, keys['nurse'])
    assert [c['verdict'] for c in result['checks']] == ['explained', 'watch', 'escalate']
    assert result['checks'][0]['received_at'] == before['checks'][0]['received_at']
    assert result['checks'][0]['id'] == before['checks'][0]['id']
    assert result['scenario'] == 'authored-demo'
    assert all('audio' not in c for c in result['checks'])
    assert 'nurse' not in result['capture_keys']


def test_capabilities_do_not_cross_rooms_or_roles():
    rooms = Rooms()
    a, b = rooms.create(), rooms.create()
    for token in (a['keys']['runner'], a['keys']['resident'], b['keys']['nurse'], ''):
        with pytest.raises(HTTPException) as exc:
            rooms.snapshot(a['room'], token)
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException):
            rooms.explain(a['room'], token)
    with pytest.raises(HTTPException):
        rooms.submit(a['room'], a['keys']['nurse'], submission())
    with pytest.raises(HTTPException):
        rooms.submit(a['room'], b['keys']['runner'], submission())


def test_submissions_are_idempotent_under_concurrency_and_conflicts_are_rejected():
    rooms = Rooms()
    room = rooms.create()
    rid, keys = room['room'], room['keys']
    body = submission()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: rooms.submit(rid, keys['runner'], body), range(20)))
    assert all(r == results[0] for r in results)
    assert rooms.snapshot(rid, keys['nurse'])['revision'] == 1
    for token, changed in ((keys['resident'], body), (keys['runner'],
                           body.model_copy(update={'duration_s': 21}))):
        with pytest.raises(HTTPException) as exc:
            rooms.submit(rid, token, changed)
        assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        rooms.submit(rid, keys['runner'], submission())


def test_context_requires_check_and_reapplying_it_is_idempotent():
    rooms = Rooms()
    room = rooms.create()
    with pytest.raises(HTTPException) as exc:
        rooms.explain(room['room'], room['keys']['nurse'])
    assert exc.value.status_code == 409
    rooms.submit(room['room'], room['keys']['runner'], submission())
    one = rooms.explain(room['room'], room['keys']['nurse'])
    assert rooms.explain(room['room'], room['keys']['nurse']) == one


def test_expiry_is_fixed_and_old_links_cannot_mutate_new_rooms():
    clock = [0]
    rooms = Rooms(clock=lambda: clock[0])
    old = rooms.create()
    clock[0] = 7200
    new = rooms.create()
    assert old['room'] not in rooms.rooms
    with pytest.raises(HTTPException):
        rooms.submit(old['room'], old['keys']['runner'], submission())
    assert rooms.snapshot(new['room'], new['keys']['nurse'])['checks'] == []


@pytest.mark.parametrize('duration', [0, -1, 30.001, float('nan'), float('inf')])
def test_invalid_durations_cannot_advance_scenario(duration):
    with pytest.raises(ValidationError):
        Submission(request_id=uuid4(), duration_s=duration)


def test_only_supported_context_and_receipt_fields_are_accepted():
    with pytest.raises(ValidationError):
        Explanation(tag='detected_exertion')
    with pytest.raises(ValidationError):
        Submission(request_id=uuid4(), duration_s=20, verdict='escalate')


def test_rooms_are_bounded():
    rooms = Rooms()
    for _ in range(128):
        rooms.create()
    with pytest.raises(HTTPException) as exc:
        rooms.create()
    assert exc.value.status_code == 429
