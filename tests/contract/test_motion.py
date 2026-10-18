import hashlib
import json
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import synthetic_token
from patient_memory.checks import scoring_context
from patient_memory.lifecycle import purge_once
from patient_memory.storage import transaction
from tests.integration.test_assessments import SLOW, seed_checks, store
from tests.unit.test_motion import payload


def client(sandbox, role="nurse"):
    cfg, _, actors, objects = sandbox
    result = TestClient(create_app(cfg, objects=objects, transcriber=lambda _: []))
    result.headers["Authorization"] = "Bearer " + synthetic_token(actors[role], cfg)
    return result


def grant(sandbox, scope="motion_check", status="granted"):
    response = client(sandbox).post(f"/v1/patients/{sandbox[1]}/consents", json={
        "scope": scope, "status": status, "decided_by": "resident"})
    assert response.status_code == 201, response.text


def capture(sandbox, role="nurse", **changes):
    return client(sandbox, role).post(f"/v1/patients/{sandbox[1]}/motion-checks",
                                      json=payload(**changes))


def test_motion_consent_is_separate_unknown_and_withdrawal_blocks_before_object_work(
        sandbox, monkeypatch):
    c = client(sandbox)
    endpoint = f"/v1/patients/{sandbox[1]}/motion-checks"
    monkeypatch.setattr(sandbox[3], "put", lambda *a: pytest.fail("capture published without consent"))
    assert c.get(endpoint + "/readiness").status_code == 403
    assert capture(sandbox).status_code == 403  # fixture grants voice only, never motion.
    grant(sandbox)
    assert c.get(endpoint + "/readiness").json() == {"ready": True}
    grant(sandbox, status="withdrawn")
    assert capture(sandbox).status_code == 403
    with psycopg.connect(sandbox[0].admin_database_url) as admin:
        assert admin.execute("SELECT count(*) FROM motion_checks WHERE patient_id=%s",
                             (sandbox[1],)).fetchone()[0] == 0
        assert admin.execute("SELECT count(*) FROM audit WHERE patient_id=%s "
                             "AND action='check_blocked_consent'", (sandbox[1],)).fetchone()[0] == 3


@pytest.mark.parametrize("role", ["patient", "admin"])
def test_motion_authorization_precedes_capture_and_evidence_work(sandbox, monkeypatch, role):
    monkeypatch.setattr(sandbox[3], "put", lambda *a: pytest.fail("unauthorized object write"))
    assert capture(sandbox, role).status_code == 404
    assert client(sandbox, role).get(
        f"/v1/patients/{sandbox[1]}/motion-checks/{uuid4()}").status_code == 404


def test_motion_publishes_exact_immutable_client_observation_evidence(sandbox):
    grant(sandbox)
    response = capture(sandbox)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["usable"] and result["change"]["status"] == "enrolling"
    assert len(result["evidence_ids"]) == 3
    assert result["assessment"]["draft_status"] == "unavailable_multimodal_evidence"
    cfg, pid, actors, objects = sandbox
    with transaction(cfg, actors["nurse"]) as conn:
        source = conn.execute("SELECT * FROM sources WHERE id=%s", (result["source_id"],)).fetchone()
        assert source["payload"]["source_system"] == "baseline-motion-client-derived-v1"
        assert source["published_at"] is not None
        facts = conn.execute("SELECT * FROM facts WHERE source_id=%s ORDER BY start_offset",
                             (result["source_id"],)).fetchall()
        for fact in facts:
            assert source["canonical_text"][fact["start_offset"]:fact["end_offset"]] == fact["quote"]
            assert fact["experiencer"] == "patient" and fact["polarity"] == "present"
        assert len(facts) == 3
    raw = objects.get(source["object_key"], source["payload_hash"])
    assert hashlib.sha256(raw).hexdigest() == source["payload_hash"]
    assert json.loads(raw) == source["payload"]
    for evidence_id in result["evidence_ids"]:
        assert client(sandbox).get(f"/v1/patients/{pid}/evidence/{evidence_id}").status_code == 200
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(cfg, actors["nurse"]) as conn:
            conn.execute("UPDATE motion_checks SET trunk_sway=3 WHERE id=%s", (result["check_id"],))
    read = client(sandbox).get(f"/v1/patients/{pid}/motion-checks/{result['check_id']}")
    assert read.status_code == 200 and read.json()["features"] == result["features"]


def test_psw_can_submit_motion_but_receives_no_measurements_or_scores(sandbox):
    grant(sandbox)
    response = capture(sandbox, "psw")
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {"check_id", "ts", "usable"}
    assert capture(sandbox, "psw", is_baseline=True).status_code == 422
    cfg, pid, actors, _ = sandbox
    endpoint = f"/v1/patients/{pid}/motion-checks/{result['check_id']}"
    assert client(sandbox, "psw").get(endpoint).status_code == 404
    with transaction(cfg, actors["psw"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM motion_checks").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
        with scoring_context(conn, pid):
            assert conn.execute("SELECT count(*) AS n FROM motion_checks").fetchone()["n"] == 1
            assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 3


def test_incomplete_or_poor_quality_capture_is_logged_without_source_or_assessment(sandbox):
    grant(sandbox)
    response = capture(sandbox, features={"sit_to_stand_s": 1.2})
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["usable"] and result["source_id"] is None and result["assessment"] is None
    assert result["features"]["step_cadence_spm"] is None
    assert result["quality"]["reasons"] == ["shoulders_unavailable", "steps_incomplete"]


def test_motion_source_retraction_and_purge_withhold_and_remove_capture(sandbox):
    grant(sandbox)
    result = capture(sandbox).json()
    cfg, pid, actors, objects = sandbox
    source = result["source_id"]
    importer = client(sandbox, "importer")
    response = importer.post(f"/v1/patients/{pid}/sources/{source}/retract",
                             json={"reason": "Synthetic capture correction"},
                             headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200
    assert client(sandbox).get(f"/v1/patients/{pid}/motion-checks/{result['check_id']}").status_code == 404
    response = importer.post(f"/v1/patients/{pid}/sources/{source}/purge",
                             json={"reason": "Synthetic capture deletion"},
                             headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE sources SET purge_after=clock_timestamp()-interval '1 second' WHERE id=%s",
                      (source,))
    assert purge_once(cfg, actors["importer"], objects)
    with psycopg.connect(cfg.admin_database_url) as admin:
        assert admin.execute("SELECT count(*) FROM motion_checks WHERE id=%s",
                             (result["check_id"],)).fetchone()[0] == 0
        assert admin.execute("SELECT count(*) FROM facts WHERE source_id=%s", (source,)).fetchone()[0] == 0


def test_motion_capture_patient_scope_and_fact_readback_cannot_cross_to_another_patient(sandbox):
    grant(sandbox)
    result = capture(sandbox).json()
    cfg, pid, actors, _ = sandbox
    other = uuid4()
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                      (other, actors["nurse"].tenant_id, "synthetic-motion-other"))
        admin.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)",
                      (actors["nurse"].tenant_id, other, actors["nurse"].principal_id))
    assert client(sandbox).get(f"/v1/patients/{other}/motion-checks/{result['check_id']}").status_code == 404
    assert client(sandbox).get(f"/v1/patients/{other}/evidence/{result['evidence_ids'][0]}").status_code == 404
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE assignments SET active=false WHERE patient_id=%s AND principal_id=%s",
                      (pid, actors["nurse"].principal_id))
    assert client(sandbox).get(f"/v1/patients/{pid}/motion-checks/{result['check_id']}").status_code == 404


def test_motion_publication_reprojects_immutable_speech_without_reviving_old_assessment(sandbox):
    grant(sandbox)
    for _ in range(3):
        response = capture(sandbox, is_baseline=True)
        assert response.status_code == 200, response.text
    seed_checks(sandbox, 6)
    voice = store(sandbox, SLOW)
    assert voice.change["status"] == "provisional"
    response = capture(sandbox, features={"sit_to_stand_s": 2.5, "trunk_sway": .12,
                                         "step_cadence_spm": 45})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["assessment"]["corroborated"]
    assert result["assessment"]["verdict"] == "escalate"
    speech = result["change"]["modalities"]["speech"]
    assert speech["check_id"] == str(voice.check_id)
    assert speech["params"]["projection"] == "immutable_capture_current_revision"
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        old = conn.execute("SELECT params FROM assessments WHERE id=%s",
                           (voice.assessment["id"],)).fetchone()
        assert old["params"]["invalidated"]
        assert conn.execute("SELECT count(*) AS n FROM assessments WHERE check_id=%s",
                            (voice.check_id,)).fetchone()["n"] == 1
        revision = conn.execute("SELECT revision FROM patients WHERE id=%s",
                                (sandbox[1],)).fetchone()["revision"]
        assert speech["params"]["source_revision"] == revision


def test_motion_helpers_are_not_generic_source_write_or_raw_public_read_capabilities(sandbox):
    grant(sandbox)
    result = capture(sandbox).json()
    cfg, pid, actors, _ = sandbox
    for role in ("psw", "nurse"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with transaction(cfg, actors[role]) as conn:
                conn.execute("SELECT pm_motion_source_payload(%s,%s)", (pid, result["check_id"]))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(cfg, actors["nurse"]) as conn:
            conn.execute("DELETE FROM motion_checks WHERE patient_id=%s", (pid,))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with transaction(cfg, actors["nurse"]) as conn:
            with scoring_context(conn, pid):
                conn.execute("SELECT pm_publish_motion_source(%s,%s,%s,%s)",
                             (pid, result["check_id"], '{}', 'foreign/key.json'))


def test_runtime_motion_rls_hides_other_tenants_and_rejects_cross_patient_source_links(
        sandbox, kaze_sandbox):
    grant(sandbox)
    result = capture(sandbox).json()
    cfg, pid, actors, _ = sandbox
    with transaction(cfg, kaze_sandbox["ids"]["service"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM motion_checks").fetchone()["n"] == 0
    other = uuid4()
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("INSERT INTO patients(id,tenant_id,external_id) VALUES(%s,%s,%s)",
                      (other, actors["nurse"].tenant_id, 'synthetic-motion-fk'))
        admin.execute("INSERT INTO assignments VALUES(%s,%s,%s,'nurse',true)",
                      (actors["nurse"].tenant_id, other, actors["nurse"].principal_id))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with transaction(cfg, actors["nurse"]) as conn:
            with scoring_context(conn, other):
                conn.execute("INSERT INTO motion_checks(tenant_id,patient_id,id,device_id,usable,"
                             "duration_s,total_frames,confident_frames,quality,sit_to_stand_s,"
                             "trunk_sway,step_cadence_spm,source_id) "
                             "VALUES(%s,%s,%s,'synthetic',true,10,100,100,'{}',1.2,.04,60,%s)",
                             (actors["nurse"].tenant_id, other, uuid4(), result["source_id"]))


def test_motion_first_publication_rejects_forged_numbers_with_correct_object_key(sandbox):
    grant(sandbox)
    cfg, pid, actors, _ = sandbox
    cid, sid = uuid4(), uuid4()
    key = f"{actors['nurse'].tenant_id}/{pid}/{sid}.json"
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with transaction(cfg, actors["nurse"]) as conn:
            with scoring_context(conn, pid):
                conn.execute("INSERT INTO motion_checks(tenant_id,patient_id,id,device_id,usable,"
                             "duration_s,total_frames,confident_frames,quality,sit_to_stand_s,"
                             "trunk_sway,step_cadence_spm,source_id) "
                             "VALUES(%s,%s,%s,'synthetic',true,10,100,100,'{}',1.2,.04,60,%s)",
                             (actors["nurse"].tenant_id, pid, cid, sid))
                raw = conn.execute("SELECT pm_motion_source_payload(%s,%s) AS payload",
                                   (pid, cid)).fetchone()["payload"]
                raw["records"][0]["value"] = "9.9"
                conn.execute("SELECT pm_publish_motion_source(%s,%s,%s,%s)",
                             (pid, cid, json.dumps(raw), key))
    with psycopg.connect(cfg.admin_database_url) as admin:
        assert admin.execute("SELECT count(*) FROM sources WHERE id=%s", (sid,)).fetchone()[0] == 0
        assert admin.execute("SELECT count(*) FROM motion_checks WHERE id=%s", (cid,)).fetchone()[0] == 0


def test_expired_motion_consent_blocks_readiness_and_publication(sandbox, monkeypatch):
    grant(sandbox)
    cfg, pid, _, objects = sandbox
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE resident_consents SET recorded_at=clock_timestamp()-interval '2 days',"
                      "expires_at=clock_timestamp()-interval '1 day' "
                      "WHERE patient_id=%s AND scope='motion_check'", (pid,))
    monkeypatch.setattr(objects, "put", lambda *a: pytest.fail("expired consent published source"))
    assert client(sandbox).get(f"/v1/patients/{pid}/motion-checks/readiness").status_code == 403
    assert capture(sandbox).status_code == 403
