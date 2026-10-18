"""Isolated Mrs. K RR example: no canonical cohort modifications or model calls."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.vitals import refresh_vitals
from patient_memory.checks import scoring_context
from patient_memory.storage import transaction
from tests.contract.test_api import client_for, import_note, source_payload
from tests.integration.test_assessments import SLOW, seed_checks, store


def rr_payload(at, *, rise=True, known_time=True):
    records = [{"concept": "resting_rr_bpm", "value": 16.0, "unit": "breaths/min",
                "effective_from": (at-timedelta(days=8-i)).isoformat() if known_time else None}
               for i in range(6)]
    records += [{"concept": "resting_rr_bpm", "value": 26.0 if rise else 16.0, "unit": "breaths/min",
                 "effective_from": time.isoformat() if known_time else None}
                for time in (at-timedelta(hours=1), at)]
    return source_payload(text=None, kind="observation", author_role="system",
                          recorded_at=datetime.now(UTC).isoformat(), effective_from=None, records=records)


def refresh(sandbox):
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        return refresh_vitals(conn, sandbox[0], sandbox[2]["nurse"], sandbox[1])


def overview(sandbox):
    response = client_for(sandbox).get(f"/v1/patients/{sandbox[1]}/overview")
    assert response.status_code == 200, response.text
    return response.json()


def example(sandbox):
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("UPDATE patients SET external_id='Mrs. K (isolated synthetic RR example)' WHERE id=%s",
                     (sandbox[1],))
    seed_checks(sandbox, 6)
    voice = store(sandbox, SLOW)
    assert voice.change["status"] == "provisional"
    result = import_note(sandbox, rr_payload(datetime.now(UTC)))
    return result


def test_isolated_mrs_k_rr_rise_is_a_corroborating_vitals_change(sandbox):
    imported = example(sandbox)
    page = overview(sandbox)
    latest = page["latest_assessment"]
    assert latest["modality"] == "vitals" and latest["corroborated"]
    assert latest["modalities"]["vitals"]["status"] == "change"
    assert latest["modalities"]["speech"]["status"] == "provisional"
    assert latest["modalities"]["vitals"]["per_feature"]["resting_rr_bpm"]["value"] == 26.0
    assert latest["modalities"]["vitals"]["params"]["threshold_status"] == "engineering_unvalidated"
    assert latest["sbar"] is None and latest["draft_status"] == "unavailable_multimodal_evidence"
    nurse = client_for(sandbox)
    for eid in latest["modalities"]["vitals"]["evidence_ids"]:
        evidence = nurse.get(f"/v1/patients/{sandbox[1]}/evidence/{eid}")
        assert evidence.status_code == 200
        assert evidence.json()["source_version_id"] == imported["source_version_id"]
        assert "26.0" in evidence.json()["quote"]


def test_repeated_refresh_is_idempotent_at_the_same_revision(sandbox):
    example(sandbox)
    first = refresh(sandbox)
    second = refresh(sandbox)
    assert first["assessment_id"] == second["assessment_id"]
    assert first["reused"] and second["reused"]


@pytest.mark.parametrize("mutation", ["retract", "purge"])
def test_source_lifecycle_withholds_old_vitals_and_next_voice_cannot_reuse_them(sandbox, mutation):
    imported = example(sandbox)
    response = client_for(sandbox, "importer").post(
        f"/v1/patients/{sandbox[1]}/sources/{imported['source_version_id']}/{mutation}",
        json={"reason": "Synthetic correction"}, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code in (200, 202)
    if mutation == "purge":
        from patient_memory.worker import run_once
        assert run_once(sandbox[0], sandbox[2]["importer"], sandbox[3])
    assert overview(sandbox)["latest_assessment"] is None
    result = store(sandbox, SLOW)
    assert not result.assessment["corroborated"]
    assert result.change["modalities"]["vitals"]["status"] == "unavailable"


def test_replacement_observations_recompute_with_current_evidence(sandbox):
    imported = example(sandbox)
    with transaction(sandbox[0], sandbox[2]["importer"]) as conn:
        payload = conn.execute("SELECT payload FROM sources WHERE id=%s",
                               (imported["source_version_id"],)).fetchone()["payload"]
    payload.update(external_version_id="2", supersedes_version_id=imported["source_version_id"])
    for record in payload["records"]:
        record["value"] = 16.0
    import_note(sandbox, payload)
    latest = overview(sandbox)["latest_assessment"]
    assert not latest["corroborated"] and latest["modalities"]["vitals"]["status"] == "none"
    assert latest["modalities"]["vitals"]["per_feature"]["resting_rr_bpm"]["value"] == 16.0


def test_unknown_event_time_does_not_become_a_resting_baseline(sandbox):
    import_note(sandbox, rr_payload(datetime.now(UTC), known_time=False))
    assert refresh(sandbox) is None
    assert overview(sandbox)["latest_assessment"] is None


def test_psw_fact_access_is_scoring_only_and_revocation_clears_it(sandbox):
    example(sandbox)
    cfg, pid, actors, objects = sandbox
    other = uuid4()
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,'Synthetic other')",
                     (other, actors["nurse"].tenant_id))
        for role in ("nurse", "importer", "psw"):
            conn.execute("INSERT INTO assignments VALUES(%s,%s,%s,%s,true)",
                         (actors[role].tenant_id, other, actors[role].principal_id, role))
    import_note((cfg, other, actors, objects), rr_payload(datetime.now(UTC)))
    with transaction(cfg, actors["psw"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
        with scoring_context(conn, pid):
            assert conn.execute("SELECT count(*) AS n FROM facts WHERE patient_id=%s", (pid,)).fetchone()["n"] == 8
            assert conn.execute("SELECT count(*) AS n FROM facts WHERE patient_id=%s", (other,)).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
    psw = client_for(sandbox, "psw")
    assert psw.get(f"/v1/patients/{pid}/overview").status_code == 404
    with transaction(cfg, actors["nurse"]) as conn:
        eid = conn.execute("SELECT id FROM facts WHERE patient_id=%s LIMIT 1", (pid,)).fetchone()["id"]
    assert psw.get(f"/v1/patients/{pid}/evidence/{eid}").status_code == 404
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("UPDATE assignments SET active=false WHERE patient_id=%s AND principal_id=%s",
                     (pid, actors["psw"].principal_id))
    with transaction(cfg, actors["psw"]) as conn:
        with scoring_context(conn, pid):
            assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0


def test_psw_voice_scoring_can_corroborate_privately_without_receipt_leak(sandbox, monkeypatch):
    from patient_memory.speech.pipeline import Analysis
    from tests.integration.test_assessments import QUALITY
    example(sandbox)
    monkeypatch.setattr("patient_memory.api.analyze", lambda *a, **k: Analysis(True, QUALITY, SLOW, [], [], {}))
    response = client_for(sandbox, "psw").post(
        f"/v1/patients/{sandbox[1]}/checks", data={"mode": "resident", "device_id": "tablet-1"},
        files={"audio": ("synthetic.wav", b"synthetic stub", "audio/wav")})
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"check_id", "ts", "usable"}
    assert overview(sandbox)["latest_assessment"]["corroborated"]
    assert client_for(sandbox, "psw").get(f"/v1/patients/{sandbox[1]}/overview").status_code == 404


def test_expired_latest_resting_observation_is_unknown_not_older_quiet_fallback(sandbox):
    at = datetime.now(UTC)
    payload = rr_payload(at-timedelta(hours=2))
    payload["records"][-1]["effective_to"] = (at-timedelta(hours=1)).isoformat()
    import_note(sandbox, payload)
    assert refresh(sandbox) is None
    seed_checks(sandbox, 6)
    result = store(sandbox, SLOW)
    assert not result.assessment["corroborated"]
    assert result.change["modalities"]["vitals"]["status"] == "unavailable"


def test_refresh_failure_preserves_source_success_and_audits_separate_error(sandbox, monkeypatch, caplog):
    def unavailable(*args, **kwargs):
        raise RuntimeError("sensitive-synthetic-marker-must-not-be-logged")
    monkeypatch.setattr("patient_memory.worker.refresh_vitals", unavailable)
    imported = example(sandbox)
    with transaction(sandbox[0], sandbox[2]["importer"]) as conn:
        job = conn.execute("SELECT status,stage,error_code FROM jobs WHERE id=%s",
                           (imported["job_id"],)).fetchone()
        assert job == {"status": "completed", "stage": "published", "error_code": None}
        audit = conn.execute("SELECT action,result FROM audit WHERE patient_id=%s AND action='vitals_refresh'",
                             (sandbox[1],)).fetchall()
        assert audit == [{"action": "vitals_refresh", "result": "error"}]
    assert "sensitive-synthetic-marker" not in caplog.text
    assert overview(sandbox)["latest_assessment"] is None
    assert refresh(sandbox)["reused"] is False
    assert overview(sandbox)["latest_assessment"]["corroborated"]
