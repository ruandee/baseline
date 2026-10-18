"""BL-31 / decision 017: consent gate on POST /checks, the PSW role, due list, skips, consent API.

The audio path is replaced by a stubbed `analyze` (no ffmpeg, no Whisper), so these run wherever
Postgres and the object store are up.
"""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for, import_note, source_payload
from tests.integration.test_assessments import QUALITY, SLOW, seed_checks

SCORE_FIELDS = {"verdict", "latest_verdict", "fused_z", "features", "change", "assessment",
                "sparkline", "sbar", "per_feature", "watch_window", "reasons", "over_budget"}


@pytest.fixture
def analyses(monkeypatch):
    """Counts audio analyses, so tests can prove consent is checked before any decode/ASR."""
    calls = []

    def fake(*args):
        calls.append(args)
        return Analysis(True, QUALITY, SLOW, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", fake)
    return calls


def upload(sandbox, role="nurse", patient=None):
    return client_for(sandbox, role).post(
        f"/v1/patients/{patient or sandbox[1]}/checks",
        data={"mode": "resident", "device_id": "tablet-1"},
        files={"audio": ("synthetic.wav", b"synthetic stub", "audio/wav")})


def admin(sandbox):
    return psycopg.connect(sandbox[0].admin_database_url, autocommit=True)


def checks_stored(sandbox):
    with admin(sandbox) as conn:
        return conn.execute("SELECT count(*) FROM voice_checks WHERE patient_id=%s",
                            (sandbox[1],)).fetchone()[0]


def audit_actions(sandbox):
    with admin(sandbox) as conn:
        return [r[0] for r in conn.execute(
            "SELECT action FROM audit WHERE patient_id=%s ORDER BY id", (sandbox[1],))]


def consent(sandbox, role="nurse", **body):
    payload = {"status": "granted", "decided_by": "resident", **body}
    return client_for(sandbox, role).post(f"/v1/patients/{sandbox[1]}/consents", json=payload)


def unconsented_patient(sandbox):
    cfg, _, actors, _ = sandbox
    pid = uuid4()
    with admin(sandbox) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                     (pid, actors["nurse"].tenant_id, f"synthetic-{pid}"))
        for role in ("importer", "nurse", "psw"):
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true)",
                         (actors["nurse"].tenant_id, pid, actors[role].principal_id, role))
    return pid


def test_fixture_consent_is_explicit_and_lets_care_team_and_psw_check(sandbox, analyses):
    view = client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/consent").json()
    assert view["state"] == "granted" and view["decided_by"] == "synthetic_fixture"
    nurse = upload(sandbox)
    assert nurse.status_code == 200, nurse.text
    assert "features" in nurse.json() and "assessment" in nurse.json()
    psw = upload(sandbox, "psw")
    assert psw.status_code == 200, psw.text
    assert set(psw.json()) == {"check_id", "ts", "usable"}, "PSW receipt carries no score"
    assert checks_stored(sandbox) == 2
    with admin(sandbox) as conn:  # the PSW's check was still scored and stored for the nurse
        assert conn.execute("SELECT count(*) FROM assessments WHERE patient_id=%s",
                            (sandbox[1],)).fetchone()[0] == 2


def test_missing_consent_is_unknown_and_blocks_before_any_audio_work(sandbox, analyses):
    pid = unconsented_patient(sandbox)
    assert client_for(sandbox).get(f"/v1/patients/{pid}/consent").json()["state"] == "unknown"
    response = upload(sandbox, patient=pid)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "consent_required"
    assert analyses == [], "no decode or ASR without consent"
    with admin(sandbox) as conn:
        assert conn.execute("SELECT count(*) FROM voice_checks WHERE patient_id=%s",
                            (pid,)).fetchone()[0] == 0
        assert conn.execute("SELECT action,result FROM audit WHERE patient_id=%s",
                            (pid,)).fetchall() == [("check_blocked_consent", "denied")]


@pytest.mark.parametrize("role", ["nurse"])
def test_withdrawal_applies_to_the_very_next_check(sandbox, analyses, role):
    assert upload(sandbox).status_code == 200
    withdrawn = consent(sandbox, role, status="withdrawn")
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["state"] == "withdrawn"
    before = len(analyses)
    for caller in ("nurse", "psw"):
        blocked = upload(sandbox, caller)
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "consent_required"
    assert len(analyses) == before and checks_stored(sandbox) == 1
    assert audit_actions(sandbox).count("check_blocked_consent") == 2
    regranted = consent(sandbox)  # latest row wins: a nurse can grant again
    assert regranted.json()["state"] == "granted"
    assert upload(sandbox).status_code == 200


def test_withdrawal_while_the_clip_is_decoded_stores_nothing(sandbox, monkeypatch):
    cfg, pid, actors, _ = sandbox

    def withdraw_during_decode(*args):
        with admin(sandbox) as conn:
            conn.execute("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,"
                         "decided_by,recorded_by) VALUES(%s,%s,%s,'voice_check','withdrawn',"
                         "'resident',%s)", (actors["nurse"].tenant_id, pid, uuid4(),
                                            actors["nurse"].principal_id))
        return Analysis(True, QUALITY, SLOW, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", withdraw_during_decode)
    response = upload(sandbox)
    assert response.status_code == 403 and response.json()["error"]["code"] == "consent_required"
    assert checks_stored(sandbox) == 0
    assert "check_blocked_consent" in audit_actions(sandbox)
    assert "create_check" not in audit_actions(sandbox)


def test_declined_and_expired_consent_block(sandbox, analyses):
    assert consent(sandbox, status="declined").json()["state"] == "declined"
    assert upload(sandbox).status_code == 403
    assert consent(sandbox).json()["state"] == "granted"  # latest row wins
    cfg, _, actors, _ = sandbox
    pid = unconsented_patient(sandbox)
    with admin(sandbox) as conn:
        past = datetime.now(UTC) - timedelta(hours=2)
        conn.execute("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,"
                     "decided_by,recorded_by,recorded_at,expires_at) VALUES(%s,%s,%s,"
                     "'voice_check','granted','resident',%s,%s,%s)",
                     (actors["nurse"].tenant_id, pid, uuid4(), actors["nurse"].principal_id,
                      past + timedelta(hours=1), past + timedelta(hours=1, minutes=30)))
    assert client_for(sandbox).get(f"/v1/patients/{pid}/consent").json()["state"] == "expired"
    assert upload(sandbox, patient=pid).status_code == 403
    future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    renewed = client_for(sandbox).post(f"/v1/patients/{pid}/consents", json={
        "status": "granted", "decided_by": "resident", "expires_at": future})
    assert renewed.json()["state"] == "granted"
    assert upload(sandbox, patient=pid).status_code == 200


def test_vox_scope_is_separate_from_voice_check_consent(sandbox):
    view = client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/consent?scope=vox_encounter")
    assert view.json()["state"] == "unknown"


def test_consent_write_permissions(sandbox):
    assert consent(sandbox, "psw").status_code == 403, "a PSW cannot grant"
    assert consent(sandbox, "psw", status="declined").status_code == 403
    assert consent(sandbox, "psw", status="withdrawn").status_code == 403
    assert consent(sandbox, "nurse", decided_by="synthetic_fixture").status_code == 403
    assert consent(sandbox, "importer", decided_by="synthetic_fixture").status_code == 201
    assert consent(sandbox, "patient").status_code == 404
    assert consent(sandbox, "admin").status_code == 404
    assert consent(sandbox, decided_by="substitute_decision_maker").status_code == 422
    assert consent(sandbox, decided_by="substitute_decision_maker",
                   sdm_reference="synthetic-sdm-1").status_code == 201
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert consent(sandbox, expires_at=past).status_code == 422
    assert consent(sandbox, status="withdrawn",
                   expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat()).status_code == 422


def test_other_roles_cannot_submit_checks(sandbox, analyses):
    for role in ("patient", "admin"):
        assert upload(sandbox, role).status_code == 404
    assert upload(sandbox, patient=uuid4()).status_code == 404
    assert analyses == []


def test_due_list_is_score_free_and_tracks_checks_skips_and_consent(sandbox, analyses):
    seed_checks(sandbox, 6, days_ago_start=8)
    client = client_for(sandbox, "psw")
    body = client.get("/v1/checks/due").json()
    assert set(body) == {"day_start", "residents"}
    [row] = body["residents"]
    assert set(row) == {"patient_id", "display_name", "status", "consent_state",
                        "last_check_ts", "skipped_today", "observation_helped"}
    assert not SCORE_FIELDS & set(row)
    assert row["status"] == "due" and row["consent_state"] == "granted"
    assert row["observation_helped"] is None, "unknown, never a claimed negative"
    skip = client.post(f"/v1/patients/{sandbox[1]}/checks/skips", json={"reason": "asleep"})
    assert skip.status_code == 201, skip.text
    assert client.get("/v1/checks/due").json()["residents"][0]["status"] == "skipped"
    assert upload(sandbox, "psw").status_code == 200
    assert client.get("/v1/checks/due").json()["residents"][0]["status"] == "done"
    assert consent(sandbox, status="withdrawn").status_code == 201
    row = client.get("/v1/checks/due").json()["residents"][0]
    assert row["status"] == "consent_needed" and row["consent_state"] == "withdrawn"
    assert "check_skipped" in audit_actions(sandbox)


def test_due_list_is_scoped_to_assigned_patients(sandbox):
    for role in ("patient", "admin"):
        assert client_for(sandbox, role).get("/v1/checks/due").json()["residents"] == []
    assert len(client_for(sandbox, "nurse").get("/v1/checks/due").json()["residents"]) == 1


def test_skips_validate_and_authorize(sandbox):
    client = client_for(sandbox, "psw")
    assert client.post(f"/v1/patients/{sandbox[1]}/checks/skips",
                       json={"reason": "bored"}).status_code == 422
    assert client.post(f"/v1/patients/{uuid4()}/checks/skips",
                       json={"reason": "other"}).status_code == 404
    assert client_for(sandbox, "patient").post(f"/v1/patients/{sandbox[1]}/checks/skips",
                                               json={"reason": "other"}).status_code == 404


def test_psw_cannot_read_scores_verdicts_overview_or_records(sandbox, analyses):
    seed_checks(sandbox, 6)
    assert upload(sandbox).status_code == 200  # an assessment and template SBAR exist
    psw = client_for(sandbox, "psw")
    pid = sandbox[1]
    assert psw.get("/v1/watchlist").status_code == 404
    assert psw.get(f"/v1/patients/{pid}/overview").status_code == 404
    assert psw.get(f"/v1/patients/{pid}/consent").status_code == 404
    assert psw.get(f"/v1/patients/{pid}/timeline").status_code == 404
    assert psw.get(f"/v1/patients/{pid}/evidence/{uuid4()}").status_code == 404
    assert psw.post(f"/v1/patients/{pid}/questions", json={"question": "sleep"}).status_code == 404
    # The nurse keeps both, and a nurse who is also a PSW elsewhere is not locked out.
    assert client_for(sandbox).get("/v1/watchlist").status_code == 200
    assert client_for(sandbox).get(f"/v1/patients/{pid}/overview").status_code == 200


def test_psw_ordinary_runtime_transaction_cannot_read_scoring_data(sandbox, analyses):
    cfg, pid, actors, _ = sandbox
    import_note(sandbox, source_payload("Patient had poor sleep."))
    seed_checks(sandbox, 6)
    assert upload(sandbox, "psw").status_code == 200
    with transaction(cfg, actors["psw"]) as conn:
        for table in ("voice_checks", "assessments", "sources", "context_tags", "facts"):
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        assert conn.execute("SELECT pm_last_check_at(%s) AS ts", (pid,)).fetchone()["ts"]
        assert conn.execute("SELECT pm_last_check_at(%s) AS ts", (uuid4(),)).fetchone()["ts"] is None
    with admin(sandbox) as conn:
        assert conn.execute("SELECT principal_id FROM audit WHERE patient_id=%s AND "
                            "action='create_check'", (pid,)).fetchall() == [(actors["psw"].principal_id,)]


def test_consent_and_skips_are_append_only_in_runtime_role(sandbox):
    cfg, pid, actors, _ = sandbox
    for table in ("resident_consents", "check_skips"):
        for statement in (f"UPDATE {table} SET recorded_at=clock_timestamp() WHERE patient_id=%s",
                          f"DELETE FROM {table} WHERE patient_id=%s"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with transaction(cfg, actors["importer"]) as conn:
                    conn.execute(statement, (pid,))


def test_revocation_during_decode_blocks_psw_publication(sandbox, monkeypatch):
    cfg, pid, actors, _ = sandbox

    def revoke(*args):
        with admin(sandbox) as conn:
            conn.execute("UPDATE assignments SET active=false WHERE patient_id=%s "
                         "AND principal_id=%s", (pid, actors["psw"].principal_id))
        return Analysis(True, QUALITY, SLOW, [], [], {})
    monkeypatch.setattr("patient_memory.api.analyze", revoke)
    assert upload(sandbox, "psw").status_code == 404
    assert checks_stored(sandbox) == 0


def test_psw_cannot_enroll_or_submit_as_live(sandbox, analyses):
    for fields in ({"mode": "live"}, {"mode": "resident", "is_baseline": "true"}):
        response = client_for(sandbox, "psw").post(f"/v1/patients/{sandbox[1]}/checks",
            data={"device_id": "synthetic", **fields}, files={"audio": ("a", b"x", "audio/wav")})
        assert response.status_code == 422
    assert analyses == []


def test_other_tenant_cannot_obtain_due_metadata_or_consent(sandbox, analyses):
    tenant, pid = uuid4(), uuid4()
    with admin(sandbox) as conn:
        conn.execute("INSERT INTO tenants VALUES(%s,'synthetic-other')", (tenant,))
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'other')",
                     (pid, tenant))
    psw = client_for(sandbox, "psw")
    assert str(pid) not in psw.get("/v1/checks/due").text
    assert upload(sandbox, "psw", patient=pid).status_code == 404
    assert client_for(sandbox).get(f"/v1/patients/{pid}/consent").status_code == 404
    assert psw.post(f"/v1/patients/{pid}/checks/skips", json={"reason": "other"}).status_code == 404
    cfg, _, actors, _ = sandbox
    with transaction(cfg, actors["psw"]) as conn:
        assert conn.execute("SELECT pm_last_check_at(%s) AS ts", (pid,)).fetchone()["ts"] is None
    assert analyses == []
