from uuid import uuid4

from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import synthetic_token
from patient_memory.domain import now
from patient_memory.worker import run_once


def client_for(sandbox, role="nurse", generator=None):
    cfg, pid, actors, objects = sandbox
    app = create_app(cfg, objects, generator)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + synthetic_token(actors[role], cfg)
    return client


def source_payload(text="Patient reports improved sleep.", **changes):
    return {"external_document_id": str(uuid4()), "external_version_id": "1", "source_system": "synthetic",
            "kind": "nursing_note", "author_role": "nurse", "visibility": "care_team",
            "recorded_at": now().isoformat(), "effective_from": "2026-01-01T00:00:00Z",
            "text": text, **changes}


def import_note(sandbox, payload=None):
    client = client_for(sandbox, "importer")
    response = client.post(f"/v1/patients/{sandbox[1]}/sources", json=payload or source_payload(),
                           headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 202, response.text
    run_once(sandbox[0], sandbox[2]["importer"], sandbox[3])
    return response.json()


def test_api_vertical_slice_and_exact_evidence(sandbox):
    job = import_note(sandbox)
    client = client_for(sandbox)
    root = f"/v1/patients/{sandbox[1]}"
    response = client.post(root + "/questions", json={"question": "How was sleep?"})
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["claims"][0]["text"] == "Patient reports improved sleep."
    assert answer["claims"][0]["epistemic_status"] == "uncertain"
    evidence_id = answer["evidence"][0]["evidence_id"]
    assert client.get(root + "/evidence/" + evidence_id).status_code == 200
    assert client.get(root + "/jobs/" + job["job_id"]).json()["status"] == "completed"
    assert client.get(root + "/timeline").json()["events"]
    missing = client.post(root + "/questions", json={"question": "allergies"}).json()
    assert missing["status"] == "insufficient_evidence" and not missing["claims"]


def test_role_boundaries_invalid_input_and_auth(sandbox):
    for role in ["nurse", "patient", "admin"]:
        client = client_for(sandbox, role)
        assert client.post(f"/v1/patients/{sandbox[1]}/sources", json=source_payload(),
                           headers={"Idempotency-Key": "x"}).status_code == 404
    client = client_for(sandbox)
    assert client.post(f"/v1/patients/{uuid4()}/questions", json={"question": "sleep"}).status_code == 404
    assert client.post(f"/v1/patients/{sandbox[1]}/questions", json={"question": ""}).status_code == 422
    assert client.get(f"/v1/patients/{sandbox[1]}/timeline?as_of=2026-01-01").status_code == 422
    assert client.post(f"/v1/patients/{sandbox[1]}/questions", content="{",
                       headers={"Content-Type": "application/json"}).status_code == 400
    client.headers.pop("Authorization")
    assert client.get("/v1/health/live").status_code == 200
    assert client.get(f"/v1/patients/{sandbox[1]}/timeline").status_code == 401


def test_payload_limit_without_content_length(sandbox):
    client = client_for(sandbox)
    response = client.post(f"/v1/patients/{sandbox[1]}/questions", content=b"x" * (2 * 1024 * 1024 + 1))
    assert response.status_code == 413


def test_summary_contract_and_pagination(sandbox):
    import_note(sandbox, source_payload("Sleep improved. Appetite improved. Mobility improved."))
    client = client_for(sandbox)
    root = f"/v1/patients/{sandbox[1]}"
    first = client.get(root + "/timeline?limit=1").json()
    assert len(first["events"]) == 1 and first["next_cursor"]
    second = client.get(root + "/timeline", params={"cursor": first["next_cursor"], "limit": 1}).json()
    assert second["events"][0]["evidence_id"] != first["events"][0]["evidence_id"]
    response = client.post(root + "/summaries", json={"shift_start": "2025-12-31T00:00:00Z",
                                                    "shift_end": now().isoformat()})
    assert response.status_code == 200, response.text
    assert len(response.json()["claims"]) == 3
