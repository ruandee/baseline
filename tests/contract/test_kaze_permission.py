"""Accepted ADR032: explicit safety-custodian voice permission, never fixture inference."""
from uuid import uuid4

import psycopg
import pytest

from patient_memory.auth import Identity, synthetic_token
from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for
from tests.contract.test_sessions import arm, client
from tests.integration.test_assessments import BASE, QUALITY


def clear_fixture_permission(k):
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        conn.execute("DELETE FROM resident_consents WHERE tenant_id=%s AND scope='voice_check'",
                     (k["tenant"],))


def decide(k, status, *, who="person", patient=None, scope="voice_check", maker="resident"):
    body = {"scope": scope, "status": status, "decided_by": maker}
    if maker == "substitute_decision_maker":
        body["sdm_reference"] = "synthetic-reference"
    return client(k, who).post(f"/v1/patients/{patient or k['patient']}/consents", json=body)


def permission(k):
    return client(k).get(f"/v1/patients/{k['patient']}/consent?scope=voice_check").json()


def upload(k, sid):
    return client(k).post(f"/v1/patients/{k['patient']}/checks",
                          data={"mode": "live", "device_id": "synthetic-kaze",
                                "session_id": sid, "is_baseline": "true"},
                          files={"audio": ("synthetic.wav", b"synthetic stub", "audio/wav")})


def test_safety_custodian_explicitly_grants_declines_and_withdraws_standing_voice_permission(kaze_sandbox):
    k = kaze_sandbox
    clear_fixture_permission(k)
    assert permission(k)["state"] == "unknown"
    for status in ("granted", "declined", "withdrawn"):
        response = decide(k, status)
        assert response.status_code == 201, response.text
        assert response.json()["state"] == status
        assert response.json()["decided_by"] == "resident"
        assert permission(k)["state"] == status
    with transaction(k["cfg"], k["ids"]["person"]) as conn:
        rows = conn.execute("SELECT status,decided_by,recorded_by FROM resident_consents "
                            "WHERE patient_id=%s ORDER BY recorded_at", (k["patient"],)).fetchall()
        assert [r["status"] for r in rows] == ["granted", "declined", "withdrawn"]
        assert all(r["decided_by"] == "resident" and r["recorded_by"] == k["ids"]["person"].principal_id
                   for r in rows)


@pytest.mark.parametrize("scope,maker", [("motion_check", "resident"), ("vox_encounter", "resident"),
                                        ("voice_check", "substitute_decision_maker")])
def test_safety_custodian_does_not_gain_other_scopes_or_sdm_authority(kaze_sandbox, scope, maker):
    k = kaze_sandbox
    assert decide(k, "granted", scope=scope, maker=maker).status_code == 403
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(k["cfg"], k["ids"]["person"]) as conn:
            conn.execute("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,"
                         "decided_by,sdm_reference,recorded_by) VALUES(%s,%s,%s,%s,'granted',%s,%s,%s)",
                         (k["tenant"], k["patient"], uuid4(), scope, maker,
                          "synthetic-reference" if maker == "substitute_decision_maker" else None,
                          k["ids"]["person"].principal_id))


def test_resident_tenant_importer_and_psw_get_no_new_consent_write_permission(sandbox):
    for role in ("importer", "psw"):
        response = client_for(sandbox, role).post(f"/v1/patients/{sandbox[1]}/consents", json={
            "scope": "voice_check", "status": "granted", "decided_by": "resident"})
        assert response.status_code == 403


def test_safety_psw_foreign_and_revoked_custody_fail_closed(kaze_sandbox, sandbox):
    k = kaze_sandbox
    assert decide(k, "granted", patient=k["other_patient"]).status_code == 404
    assert decide(k, "granted", who="admin").status_code == 404
    assert client_for(sandbox, "importer").post(f"/v1/patients/{k['patient']}/consents", json={
        "scope": "voice_check", "status": "granted", "decided_by": "resident"}).status_code == 404
    psw = uuid4()
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-safety-psw')",
                     (psw, k["tenant"]))
        conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'psw',true)",
                     (k["tenant"], k["patient"], psw))
    psw_client = client(k)
    psw_client.headers["Authorization"] = "Bearer " + synthetic_token(Identity(psw, k["tenant"]), k["cfg"])
    assert psw_client.post(f"/v1/patients/{k['patient']}/consents", json={
        "scope": "voice_check", "status": "granted", "decided_by": "resident"}).status_code == 403
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        conn.execute("UPDATE assignments SET active=false WHERE tenant_id=%s AND patient_id=%s "
                     "AND principal_id=%s", (k["tenant"], k["patient"], k["ids"]["person"].principal_id))
    assert decide(k, "granted").status_code == 404


def test_custody_uses_assigned_importer_boundary_not_equal_uuid_guessing(kaze_sandbox):
    k = kaze_sandbox
    assert k["ids"]["person"].principal_id != k["other_patient"]
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,'importer',true)",
                     (k["tenant"], k["other_patient"], k["ids"]["person"].principal_id))
    assert arm(k, patient=k["other_patient"]).status_code == 201
    assert decide(k, "granted", patient=k["other_patient"]).status_code == 201


def test_runtime_insert_policy_matches_exact_custody_and_recording_actor(kaze_sandbox):
    k = kaze_sandbox
    clear_fixture_permission(k)
    statement = ("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,decided_by,"
                 "recorded_by) VALUES(%s,%s,%s,'voice_check','granted','resident',%s)")
    actor = k["ids"]["person"]
    with transaction(k["cfg"], actor) as conn:
        assert conn.execute("SELECT pm_safety_voice_custodian(%s) AS ok",
                            (k["patient"],)).fetchone()["ok"] is True
        conn.execute(statement, (k["tenant"], k["patient"], uuid4(), actor.principal_id))
    assert permission(k)["state"] == "granted"
    for tenant, patient, recorded_by in [
            (uuid4(), k["patient"], actor.principal_id),
            (k["tenant"], k["other_patient"], actor.principal_id),
            (k["tenant"], k["patient"], k["ids"]["service"].principal_id)]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(k["cfg"], actor) as conn:
                conn.execute(statement, (tenant, patient, uuid4(), recorded_by))


def test_arming_and_ending_never_create_or_withdraw_standing_voice_permission(kaze_sandbox):
    k = kaze_sandbox
    clear_fixture_permission(k)
    for expected in ("unknown", "granted"):
        if expected == "granted":
            assert decide(k, expected).status_code == 201
        response = arm(k)
        assert response.status_code == 201
        assert permission(k)["state"] == expected
        assert client(k).post(f"/v1/patients/{k['patient']}/sessions/{response.json()['id']}/end",
                              json={}).status_code == 200
        assert permission(k)["state"] == expected


def test_unknown_and_withdrawn_voice_permission_block_before_decode(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    clear_fixture_permission(k)
    sid = arm(k).json()["id"]
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **kw: pytest.fail("no audio processing"))
    assert upload(k, sid).status_code == 403
    assert decide(k, "withdrawn").status_code == 201
    assert upload(k, sid).status_code == 403


def test_withdrawal_during_processing_blocks_publication_without_counting_profile(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    clear_fixture_permission(k)
    assert decide(k, "granted").status_code == 201
    sid = arm(k).json()["id"]
    def analyze(*args, **kwargs):
        assert decide(k, "withdrawn").status_code == 201
        return Analysis(True, QUALITY, BASE, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", analyze)
    assert upload(k, sid).status_code == 403
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        assert conn.execute("SELECT count(*) FROM voice_checks WHERE patient_id=%s",
                            (k["patient"],)).fetchone()[0] == 0


def test_explicit_voice_permission_admits_session_capture_without_counting_profile(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    clear_fixture_permission(k)
    assert decide(k, "granted").status_code == 201
    sid = arm(k).json()["id"]
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **kw: Analysis(True, QUALITY, BASE, [], [], {}))
    response = upload(k, sid)
    assert response.status_code == 200, response.text
    assert response.json()["session"]["baseline_usable"] == 1
    with psycopg.connect(k["cfg"].admin_database_url) as conn:
        assert conn.execute("SELECT count(*) FROM resident_check_profiles WHERE patient_id=%s",
                            (k["patient"],)).fetchone()[0] == 0
