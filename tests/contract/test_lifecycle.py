from uuid import uuid4

from patient_memory.generation import ExtractiveGenerator
from patient_memory.storage import transaction
from patient_memory.worker import run_once
from tests.contract.test_api import client_for, import_note, source_payload


def test_cache_revocation_and_visibility_changes(sandbox):
    imported = import_note(sandbox, source_payload(visibility="patient_and_care_team"))
    cfg, pid, actors, _ = sandbox
    patient = client_for(sandbox, "patient")
    importer = client_for(sandbox, "importer")
    root = f"/v1/patients/{pid}"
    query = {"question": "sleep", "as_of": "2026-02-01T00:00:00Z"}
    from patient_memory.domain import now
    query["known_at"] = now().isoformat()
    first = patient.post(root + "/questions", json=query)
    assert first.status_code == 200, first.text
    assert patient.post(root + "/questions", json=query).json()["claims"]
    assert importer.put(root + "/sources/" + imported["source_version_id"] + "/visibility",
                        json={"visibility": "care_team"}, headers={"Idempotency-Key": str(uuid4())}).status_code == 200
    assert not patient.post(root + "/questions", json=query).json()["claims"]
    assert patient.get(root + "/evidence/" + first.json()["evidence"][0]["evidence_id"]).status_code == 404
    with transaction(cfg, actors["importer"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM answers WHERE principal_id=%s",
                            (actors["patient"].principal_id,)).fetchone()["n"] == 1


def test_assignment_revoked_during_generation(sandbox):
    import_note(sandbox)
    cfg, pid, actors, _ = sandbox
    admin = client_for(sandbox, "admin")

    class RevokingGenerator(ExtractiveGenerator):
        def generate(self, *args):
            claims = super().generate(*args)
            response = admin.put(f"/v1/patients/{pid}/assignments", json={
                "principal_id": str(actors["nurse"].principal_id), "role": "nurse", "active": False})
            assert response.status_code == 200, response.text
            return claims

    client = client_for(sandbox, generator=RevokingGenerator())
    assert client.post(f"/v1/patients/{pid}/questions", json={"question": "sleep"}).status_code == 404


def test_retraction_purge_and_cursor_revision(sandbox):
    imported = import_note(sandbox, source_payload("Sleep improved. Appetite improved."))
    cfg, pid, actors, objects = sandbox
    nurse, importer = client_for(sandbox), client_for(sandbox, "importer")
    root = f"/v1/patients/{pid}"
    page = nurse.get(root + "/timeline?limit=1").json()
    response = importer.post(root + "/sources/" + imported["source_version_id"] + "/purge",
                             json={"reason": "synthetic deletion test"}, headers={"Idempotency-Key": "purge-test"})
    assert response.status_code == 202, response.text
    assert nurse.get(root + "/timeline", params={"cursor": page["next_cursor"]}).status_code == 409
    assert not nurse.post(root + "/questions", json={"question": "sleep"}).json()["claims"]
    assert run_once(cfg, actors["importer"], objects)
    with transaction(cfg, actors["importer"]) as conn:
        source = conn.execute("SELECT * FROM sources WHERE id=%s", (imported["source_version_id"],)).fetchone()
        assert source["purged_at"] and source["canonical_text"] == "" and source["payload"] == {}
        assert not conn.execute("SELECT * FROM facts WHERE source_id=%s", (source["id"],)).fetchall()
        import pytest
        from botocore.exceptions import ClientError
        with pytest.raises(ClientError):
            objects.client.get_object(Bucket=cfg.object_bucket, Key=source["object_key"])


def test_rate_limit_is_shared_across_app_instances(sandbox):
    cfg, pid, _, _ = sandbox
    cfg.rate_limit = 1
    first, second = client_for(sandbox), client_for(sandbox)
    root = f"/v1/patients/{pid}/questions"
    assert first.post(root, json={"question": "sleep"}).status_code == 200
    blocked = second.post(root, json={"question": "sleep"})
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
