from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.config import Settings
from scripts.frontend_demo import prepare_session


def test_frontend_shell_contains_no_credentials_and_api_requires_identity():
    client = TestClient(create_app(Settings()))
    response = client.get("/app/")
    assert response.status_code == 200
    assert "Shift handoff" in response.text
    assert "eyJ" not in response.text
    assert client.get("/app/app.js").status_code == 200
    assert client.post("/v1/patients", json={"external_id": "synthetic-browser"}).status_code == 401


def test_demo_session_can_read_but_cannot_import_or_read_foreign_patient(sandbox):
    cfg, foreign_patient, _, _ = sandbox
    entries = prepare_session(cfg)
    client = TestClient(create_app(cfg))
    headers = {"Authorization": "Bearer " + entries[0]["token"]}
    root = "/v1/patients/" + entries[0]["patient_id"]
    response = client.post(root + "/summaries", headers=headers, json={
        "shift_start": "2026-01-02T00:00:00Z", "shift_end": "2026-01-02T23:59:59Z"})
    assert response.status_code == 200
    answer = response.json()
    assert answer["versions"]["model"] == "extractive-stub-v1"
    assert answer["claims"]
    eid = answer["claims"][0]["evidence_ids"][0]
    assert client.get(root + "/evidence/" + eid, headers=headers).status_code == 200
    assert client.get(f"/v1/patients/{foreign_patient}/timeline", headers=headers).status_code == 404
    response = client.post(root + "/sources", headers={**headers, "Idempotency-Key": "no-write"}, json={
        "external_document_id": "synthetic-browser", "external_version_id": "1",
        "source_system": "synthetic", "kind": "nursing_note", "author_role": "nurse",
        "recorded_at": "2026-01-02T08:00:00Z", "text": "This must not be imported."})
    assert response.status_code == 404
