from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.auth import Identity, synthetic_token
from patient_memory.config import Settings
from scripts.demo_explain import PATIENT, register
from scripts.seed import uid


@pytest.mark.parametrize("role,patient", [("psw", PATIENT), ("nurse", uuid4())])
def test_explanation_denies_other_roles_or_patients_before_storage(role, patient, monkeypatch):
    from scripts import demo_explain

    def forbidden(*args, **kwargs):
        pytest.fail("Storage must not be accessed for a denied role or patient")

    monkeypatch.setattr(demo_explain, "transaction", forbidden)
    cfg = Settings()
    reader = Identity(uid("0/nurse"), uid("tenant-0"))
    app = create_app(cfg)
    register(app, cfg, reader)
    actor = Identity(uid(f"0/{role}"), reader.tenant_id)
    response = TestClient(app).post(f"/demo/residents/{patient}/context", json={
        "assessment_id": str(uuid4()), "kind": "explainer", "tag": "dentures",
        "label": "Synthetic observed context", "valid_from": "2026-10-18T12:00:00Z",
    }, headers={"Authorization": "Bearer " + synthetic_token(actor, cfg),
                "X-PM-Demo": "1", "Idempotency-Key": str(uuid4())})
    assert response.status_code == 404
