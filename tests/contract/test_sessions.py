"""KAZE session endpoints and session check-ins (decision 018)."""
import shutil
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import synthetic_token
from patient_memory.speech.pipeline import Analysis
from tests.contract.test_checks import USABLE, encode, on_script
from tests.integration.test_assessments import BASE, QUALITY, SLOW

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
CONTACTS = [{"name": "Dee", "phone_e164": "+14165550101"},
            {"name": "Eve", "phone_e164": "+14165550102"}]


def client(k, who="person"):
    c = TestClient(create_app(k["cfg"], k["objects"], transcriber=on_script))
    c.headers["Authorization"] = "Bearer " + synthetic_token(k["ids"][who], k["cfg"])
    return c


def body(**fields):
    ends = datetime.now(UTC) + timedelta(hours=3)
    return {"display_name": "Sam", "ends_at": ends.isoformat(), "interval_min": 1,
            "contacts": CONTACTS, "context_tags": ["exertion"], **fields}


def arm(k, who="person", patient=None, **fields):
    return client(k, who).post(f"/v1/patients/{patient or k['patient']}/sessions", json=body(**fields))


def admin_rows(k, sql, params):
    with psycopg.connect(k["cfg"].admin_database_url) as admin:
        return admin.execute(sql, params).fetchall()


def test_arming_returns_an_arming_session_with_masked_contacts(kaze_sandbox):
    k = kaze_sandbox
    response = arm(k)
    assert response.status_code == 201, response.text
    s = response.json()
    assert s["status"] == "arming" and s["patient_id"] == str(k["patient"])
    assert s["baseline"] == {"required": 3, "usable": 0}
    assert s["next_due_at"] is None and s["activated_at"] is None and s["ladder_level"] == 0
    assert s["interval_min"] == 1 and s["context_tags"] == ["exertion"]
    assert s["contacts"] == [{"contact_index": 1, "name": "Dee", "phone_masked": "+*******0101"},
                             {"contact_index": 2, "name": "Eve", "phone_masked": "+*******0102"}]
    assert "4165550101" not in response.text
    assert admin_rows(k, "SELECT action FROM audit WHERE patient_id=%s", (k["patient"],)) == [
        ("arm_session",)]


def test_only_the_person_can_arm_and_only_in_a_safety_tenant(kaze_sandbox, sandbox):
    k = kaze_sandbox
    assert arm(k, "service").status_code == 404  # care team cannot arm
    assert arm(k, "admin").status_code == 404
    assert arm(k, patient=k["other_patient"]).status_code == 404  # someone else's row
    cfg, resident, actors, objects = sandbox
    resident_client = TestClient(create_app(cfg, objects, transcriber=on_script))
    resident_client.headers["Authorization"] = "Bearer " + synthetic_token(actors["importer"], cfg)
    assert resident_client.post(f"/v1/patients/{resident}/sessions",
                                json=body()).status_code == 404


def test_a_second_open_session_is_409_until_the_first_ends(kaze_sandbox):
    k = kaze_sandbox
    first = arm(k).json()
    assert arm(k).json()["error"]["code"] == "session_open"
    ended = client(k).post(f"/v1/patients/{k['patient']}/sessions/{first['id']}/end", json={})
    assert ended.status_code == 200 and ended.json()["status"] == "ended"
    assert arm(k).status_code == 201


@pytest.mark.parametrize("fields", [
    {"ends_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat()},
    {"ends_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(), "interval_min": 45},
    {"ends_at": (datetime.now(UTC) + timedelta(hours=25)).isoformat()},
    {"contacts": []},
    {"context_tags": ["marathon"]},
    {"escalation_enabled": "maybe"},
])
def test_invalid_arm_requests_are_422_and_store_nothing(kaze_sandbox, fields):
    k = kaze_sandbox
    response = arm(k, **fields)
    assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_request"
    assert admin_rows(k, "SELECT id FROM safety_sessions WHERE patient_id=%s", (k["patient"],)) == []


def test_idempotent_arm_replays_and_conflicts(kaze_sandbox):
    k = kaze_sandbox
    c, payload = client(k), body()
    url = f"/v1/patients/{k['patient']}/sessions"
    first = c.post(url, json=payload, headers={"Idempotency-Key": "arm-1"})
    again = c.post(url, json=payload, headers={"Idempotency-Key": "arm-1"})
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    changed = c.post(url, json={**payload, "display_name": "Sammy"},
                     headers={"Idempotency-Key": "arm-1"})
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"


def test_status_is_care_team_only_and_scoped(kaze_sandbox):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    url = f"/v1/patients/{k['patient']}/sessions/{sid}"
    assert client(k).get(url).status_code == 200
    status = client(k, "service").get(url)
    assert status.status_code == 200 and status.json()["checks"] == []
    assert status.json()["escalations"] == []
    assert client(k, "other").get(url).status_code == 404
    assert client(k, "admin").get(url).status_code == 404
    # The other person's patient path cannot reach my session either.
    assert client(k, "other").get(
        f"/v1/patients/{k['other_patient']}/sessions/{sid}").status_code == 404
    assert client(k).get(f"/v1/patients/{k['patient']}/sessions/{uuid4()}").status_code == 404
    listed = client(k, "service").get(f"/v1/patients/{k['patient']}/sessions").json()
    assert [s["id"] for s in listed["sessions"]] == [sid]


def test_end_sets_the_24_hour_deletion_and_is_idempotent(kaze_sandbox):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    url = f"/v1/patients/{k['patient']}/sessions/{sid}/end"
    assert client(k, "service").post(url, json={}).status_code == 404  # only the person ends
    assert client(k).post(url, json={"reason": "x"}).status_code == 422
    first = client(k).post(url, json={}).json()
    assert first["status"] == "ended" and first["end_reason"] == "user"
    assert first["next_due_at"] is None
    ended, delete_after = (datetime.fromisoformat(first[f]) for f in ["ended_at", "delete_after"])
    assert delete_after - ended == timedelta(hours=24)
    assert client(k).post(url, json={}).json() == first


def test_location_needs_a_session_and_both_coordinates(kaze_sandbox):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    url = f"/v1/patients/{k['patient']}/checks"
    audio = {"audio": ("clip", b"not audio", "application/octet-stream")}
    for fields in [{"lat": "43.6", "lon": "-79.4"}, {"session_id": sid, "lat": "43.6"},
                   {"session_id": sid, "lat": "91", "lon": "0"}]:
        response = client(k).post(url, data={"mode": "live", "device_id": "phone",
                                             "is_baseline": "true", **fields}, files=audio)
        assert response.status_code == 422, fields


@pytest.mark.parametrize("who,fields,status", [
    ("person", {"mode": "resident", "is_baseline": "true"}, 422),
    ("person", {"is_baseline": "false"}, 422),  # arming takes baseline clips only
    ("service", {"is_baseline": "true"}, 404),  # only the person checks in
    ("other", {"is_baseline": "true"}, 404),
])
def test_session_check_ins_are_rejected_before_audio_work(kaze_sandbox, who, fields, status):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    data = {"mode": "live", "device_id": "phone", "session_id": sid, **fields}
    response = client(k, who).post(f"/v1/patients/{k['patient']}/checks", data=data,
                                   files={"audio": ("clip", b"not audio", "application/octet-stream")})
    assert response.status_code == status
    assert admin_rows(k, "SELECT id FROM voice_checks WHERE patient_id=%s", (k["patient"],)) == []


def add_past_end_session(k):
    """An active session whose ends_at passed before the retention job ran."""
    sid = uuid4()
    with psycopg.connect(k["cfg"].admin_database_url) as admin:
        admin.execute(
            "INSERT INTO safety_sessions(tenant_id,patient_id,id,display_name,status,created_at,"
            "activated_at,ends_at,next_due_at) VALUES(%s,%s,%s,'Sam','active',"
            "now()-interval '2 hours',now()-interval '2 hours',now()-interval '1 minute',now())",
            (k["tenant"], k["patient"], sid))
    return sid


def test_a_session_past_its_end_takes_no_check_ins(kaze_sandbox):
    k = kaze_sandbox
    sid = add_past_end_session(k)
    response = client(k).post(f"/v1/patients/{k['patient']}/checks",
                              data={"mode": "live", "device_id": "phone", "session_id": str(sid)},
                              files={"audio": ("clip", b"x", "application/octet-stream")})
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_ended"


def test_arming_again_closes_a_session_past_its_end(kaze_sandbox):
    k = kaze_sandbox
    old = add_past_end_session(k)
    assert arm(k).status_code == 201
    previous = client(k).get(f"/v1/patients/{k['patient']}/sessions/{old}").json()
    assert previous["status"] == "ended" and previous["end_reason"] == "expired"
    assert previous["ended_at"] == previous["ends_at"]


def test_late_end_does_not_extend_retention_past_planned_expiry(kaze_sandbox):
    k = kaze_sandbox
    sid = add_past_end_session(k)
    response = client(k).post(f"/v1/patients/{k['patient']}/sessions/{sid}/end", json={})
    assert response.status_code == 200, response.text
    ended = response.json()
    assert ended["end_reason"] == "expired" and ended["ended_at"] == ended["ends_at"]
    assert (datetime.fromisoformat(ended["delete_after"]) -
            datetime.fromisoformat(ended["ends_at"])) == timedelta(hours=24)


def test_session_expiring_during_decode_is_rejected_before_storage(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    calls = []
    def analyze(*args):
        calls.append(True)
        # A session was valid at admission, but its end passes before the storage gate.
        with psycopg.connect(k["cfg"].admin_database_url) as admin:
            admin.execute("UPDATE safety_sessions SET created_at=now()-interval '2 hours',"
                          "ends_at=now()-interval '1 minute' WHERE id=%s", (sid,))
        return Analysis(True, QUALITY, BASE, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", analyze)
    response = check_in(k, sid, b"synthetic stub", True)
    assert calls == [True]
    assert response.status_code == 409 and response.json()["error"]["code"] == "session_ended"
    assert admin_rows(k, "SELECT count(*) FROM voice_checks WHERE session_id=%s", (sid,)) == [(0,)]


@pytest.mark.parametrize("fail", [False, True])
def test_session_raw_audio_is_removed_even_with_keep_audio_enabled(kaze_sandbox, monkeypatch, fail):
    k = {**kaze_sandbox, "cfg": kaze_sandbox["cfg"].model_copy(update={"keep_audio": True})}
    sid = arm(k).json()["id"]
    directories = []
    def analyze(upload, work, **kwargs):
        directories.append(work)
        assert upload.exists()
        if fail:
            from patient_memory.speech.pipeline import InvalidAudio
            raise InvalidAudio
        return Analysis(True, QUALITY, BASE, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", analyze)
    response = check_in(k, sid, b"synthetic stub", True)
    assert response.status_code == (422 if fail else 200), response.text
    assert directories and all(not path.exists() for path in directories)


@pytest.mark.parametrize("profile", ["budget", "no_escalate"])
def test_raw_session_change_survives_pcc_budget_and_profile_for_ladder_consumers(
        kaze_sandbox, monkeypatch, profile):
    k = kaze_sandbox
    cfg = k["cfg"].model_copy(update={
        "escalation_budget": 0,
        "no_escalate_patients": str(k["patient"]) if profile == "no_escalate" else ""})
    k = {**k, "cfg": cfg}
    sid = arm(k, context_tags=[]).json()["id"]
    # A strong authored multifeature signal makes the PCC verdict eligible to escalate.
    signal = {**SLOW, "speech_rate_wpm": BASE["speech_rate_wpm"] * .6,
              "pause_ratio": BASE["pause_ratio"] + .16, "mean_pause_s": BASE["mean_pause_s"] + .4}
    features = iter([BASE, BASE, BASE, signal, signal])
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **kw: Analysis(
        True, QUALITY, next(features), [], [], {}))
    for _ in range(3):
        assert check_in(k, sid, b"synthetic stub", True).status_code == 200
    first = check_in(k, sid, b"synthetic stub", False)
    second = check_in(k, sid, b"synthetic stub", False)
    assert first.status_code == second.status_code == 200
    assert first.json()["change"]["status"] == "provisional"
    assert second.json()["change"]["status"] == "change"
    assessment = second.json()["assessment"]
    assert assessment["over_budget"] if profile == "budget" else assessment["no_escalate"]
    # BL-26 must consume this raw session change plus session explainers, not the PCC verdict.
    status = client(k).get(f"/v1/patients/{k['patient']}/sessions/{sid}").json()
    assert status["context_tags"] == [] and status["checks"][-1]["change_status"] == "change"


def test_another_persons_session_id_is_404(kaze_sandbox):
    k = kaze_sandbox
    theirs = arm(k, "other", patient=k["other_patient"]).json()["id"]
    response = client(k).post(f"/v1/patients/{k['patient']}/checks",
                              data={"mode": "live", "device_id": "phone", "session_id": theirs,
                                    "is_baseline": "true"},
                              files={"audio": ("clip", b"x", "application/octet-stream")})
    assert response.status_code == 404


@pytest.fixture(scope="module")
def usable_clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    return encode(USABLE, "webm", tmp_path_factory.mktemp("kaze"))


def check_in(k, sid, clip, is_baseline, **fields):
    return client(k).post(
        f"/v1/patients/{k['patient']}/checks",
        data={"mode": "live", "device_id": "phone", "session_id": sid,
              "is_baseline": str(is_baseline).lower(), **fields},
        files={"audio": ("clip", clip, "application/octet-stream")})


@needs_ffmpeg
def test_three_baseline_clips_activate_the_session(kaze_sandbox, usable_clip):
    k = kaze_sandbox
    sid = arm(k).json()["id"]
    for n in range(1, 4):
        response = check_in(k, sid, usable_clip, True, lat="43.65", lon="-79.38", accuracy_m="12")
        assert response.status_code == 200, response.text
        session = response.json()["session"]
        assert session["baseline_usable"] == n
        assert session["status"] == ("active" if n == 3 else "arming")
    assert session["next_due_at"]
    status = client(k).get(f"/v1/patients/{k['patient']}/sessions/{sid}").json()
    assert status["status"] == "active" and status["baseline"] == {"required": 3, "usable": 3}
    due = datetime.fromisoformat(status["next_due_at"])
    assert due - datetime.fromisoformat(status["activated_at"]) == timedelta(minutes=1)
    assert [c["has_location"] for c in status["checks"]] == [True, True, True]
    assert "43.65" not in str(status)  # coordinates are never returned
    rows = admin_rows(k, "SELECT lat,lon,accuracy_m FROM voice_checks WHERE session_id=%s", (sid,))
    assert rows == [(43.65, -79.38, 12.0)] * 3

    # A check-in after activation is scored against tonight's three baseline clips only.
    response = check_in(k, sid, usable_clip, False)
    assert response.status_code == 200, response.text
    assert response.json()["change"]["mode"] == "enrolled"
    assert response.json()["session"]["status"] == "active"
    last = client(k).get(f"/v1/patients/{k['patient']}/sessions/{sid}").json()["last_checkin_at"]
    assert datetime.fromisoformat(last) == datetime.fromisoformat(response.json()["ts"])

    # A check outside the session never borrows the session's baseline clips.
    outside = client(k).post(f"/v1/patients/{k['patient']}/checks",
                             data={"mode": "live", "device_id": "phone"},
                             files={"audio": ("clip", usable_clip, "application/octet-stream")})
    assert outside.status_code == 200 and outside.json()["change"]["mode"] == "rolling"
    assert outside.json()["session"] is None

    client(k).post(f"/v1/patients/{k['patient']}/sessions/{sid}/end", json={})
    late = check_in(k, sid, usable_clip, False)
    assert late.status_code == 409 and late.json()["error"]["code"] == "session_ended"
