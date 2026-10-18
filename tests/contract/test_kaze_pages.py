"""KAZE bootstrap is a separate, scoped, preconfigured self-custody identity."""
from uuid import uuid4

from fastapi.testclient import TestClient

from patient_memory.auth import synthetic_token
from scripts.frontend import workspace_app


def client_for(k, monkeypatch, identity=None, patient=None):
    monkeypatch.setenv("PM_DEMO_KAZE_TOKEN", synthetic_token(identity or k["ids"]["person"], k["cfg"]))
    monkeypatch.setenv("PM_DEMO_KAZE_PATIENT_ID", str(patient or k["patient"]))
    app = workspace_app(k["cfg"], k["ids"]["service"], [{"id": str(k["other_patient"]), "name": "Other"}])
    return TestClient(app, base_url="http://127.0.0.1:8001", client=("127.0.0.1", 1234))


def test_kaze_bootstrap_returns_only_the_separate_self_identity(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    client = client_for(k, monkeypatch)
    response = client.get("/demo/session", headers={"X-PM-Demo": "1", "X-PM-Role": "kaze"})
    assert response.status_code == 200
    body = response.json()
    assert body["patients"] == [{"id": str(k["patient"]), "name": "synthetic-kaze-person"}]
    assert set(body) == {"token", "patients", "provider"}
    client.headers["Authorization"] = "Bearer " + body["token"]
    assert client.get(f"/v1/patients/{k['patient']}/sessions").status_code == 200
    assert client.get(f"/v1/patients/{k['other_patient']}/sessions").status_code == 404
    for route in ["/out", f"/out/session/{uuid4()}"]:
        shell = client.get(route)
        assert shell.status_code == 200 and "kaze.js" in shell.text
        assert shell.headers["cache-control"] == "no-store"


def test_kaze_bootstrap_has_no_nurse_fallback_and_rechecks_assignment(kaze_sandbox, monkeypatch):
    k = kaze_sandbox
    for identity, patient in [(k["ids"]["service"], k["patient"]),
                               (k["ids"]["person"], k["other_patient"])]:
        client = client_for(k, monkeypatch, identity, patient)
        response = client.get("/demo/session", headers={"X-PM-Demo": "1", "X-PM-Role": "kaze"})
        assert response.status_code in (404, 503)
        assert "token" not in response.json()
    client = client_for(k, monkeypatch)
    monkeypatch.delenv("PM_DEMO_KAZE_TOKEN")
    response = client.get("/demo/session", headers={"X-PM-Demo": "1", "X-PM-Role": "kaze"})
    assert response.status_code == 503 and "token" not in response.json()


def test_kaze_bootstrap_rejects_cross_origin_before_returning_a_token(kaze_sandbox, monkeypatch):
    client = client_for(kaze_sandbox, monkeypatch)
    response = client.get("/demo/session", headers={"X-PM-Demo": "1", "X-PM-Role": "kaze",
                                                  "Origin": "https://other.example"})
    assert response.status_code == 403 and "token" not in response.json()
