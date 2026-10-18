"""BL-33: GET .../assessments/{aid}/note under RLS, with decision-015 availability."""
import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.note import (
    CHECK_SYSTEM,
    FACT_SYSTEM,
    validate_baseline_profile,
    validate_document_reference,
)
from patient_memory.baseline.sbar import enrich_assessment_sbar
from patient_memory.storage import transaction
from tests.contract.test_api import client_for, import_note
from tests.contract.test_context import post as post_context
from tests.integration.test_assessments import BASE, SLOW, seed_checks, store


def escalated(sandbox):
    seed_checks(sandbox, 6)
    response = post_context(sandbox, {
        "kind": "amplifier", "tag": "poor_intake", "label": "Poor intake",
        "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat()})
    assert response.status_code == 201, response.text
    result = store(sandbox, SLOW)
    assert result.assessment["verdict"] == "escalate"
    return result, response.json()["source_id"]


def note_path(sandbox, assessment_id):
    return f"/v1/patients/{sandbox[1]}/assessments/{assessment_id}/note"


def stored_sbar(sandbox, assessment_id):
    cfg, pid, actors, _ = sandbox
    with transaction(cfg, actors["nurse"]) as conn:
        return conn.execute("SELECT sbar FROM assessments WHERE patient_id=%s AND id=%s",
                            (pid, assessment_id)).fetchone()["sbar"]


def test_note_is_a_valid_preliminary_document_reference_with_exact_sbar(sandbox, monkeypatch):
    monkeypatch.setattr("patient_memory.baseline.llm.request_json",
                        lambda *a, **k: pytest.fail("note export must not call a model"))
    result, _ = escalated(sandbox)
    aid = result.assessment["id"]
    nurse = client_for(sandbox)
    response = nurse.get(note_path(sandbox, aid))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/fhir+json")
    note = response.json()
    sbar = stored_sbar(sandbox, aid)
    text = "\n".join(f"{s['section']}: {s['text']}" for s in sbar["sentences"])
    assert validate_document_reference(note) == []
    assert validate_baseline_profile(note, text) == []
    assert base64.b64decode(note["content"][0]["attachment"]["data"]).decode() == text
    assert note["subject"]["reference"] == f"Patient/{sandbox[1]}"
    # Fact citations open through /evidence; the check citation is signal data, not a fact.
    related = note["context"]["related"]
    facts = [r["identifier"]["value"] for r in related if r["identifier"]["system"] == FACT_SYSTEM]
    checks = [r["identifier"]["value"] for r in related if r["identifier"]["system"] == CHECK_SYSTEM]
    assert facts and checks == [str(result.check_id)]
    for fact in facts:
        assert nurse.get(f"/v1/patients/{sandbox[1]}/evidence/{fact}").status_code == 200
    cfg, pid, _, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        assert conn.execute("SELECT count(*) FROM audit WHERE patient_id=%s "
                            "AND action='note_export'", (pid,)).fetchone()[0] == 1


def test_configured_draft_exports_with_its_source(sandbox, monkeypatch):
    result, _ = escalated(sandbox)

    def request(cfg, **kwargs):
        return {"sentences": json.loads(kwargs["user"])["supported_sentences"][:4]}

    monkeypatch.setattr("patient_memory.baseline.llm.request_json", request)
    cfg = sandbox[0].model_copy(update={"provider": "compatible"})
    enrich_assessment_sbar(cfg, sandbox[2]["nurse"], sandbox[1], result.assessment["id"])
    note = client_for(sandbox).get(note_path(sandbox, result.assessment["id"])).json()
    source, = [e for e in note["extension"] if e["url"].endswith("/sbar-source")]
    assert source["valueCode"] == "gemini" and validate_document_reference(note) == []


def test_authorization_is_checked_before_retrieval(sandbox):
    result, _ = escalated(sandbox)
    aid = result.assessment["id"]
    for role in ("patient", "admin", "psw"):
        assert client_for(sandbox, role).get(note_path(sandbox, aid)).status_code == 404
    nurse = client_for(sandbox)
    assert nurse.get(f"/v1/patients/{uuid4()}/assessments/{aid}/note").status_code == 404
    assert nurse.get(note_path(sandbox, uuid4())).status_code == 404


@pytest.mark.parametrize("operation", ["retract", "visibility", "purge"])
def test_source_change_returns_unavailable_never_the_old_note(sandbox, operation):
    result, source_id = escalated(sandbox)
    aid = result.assessment["id"]
    nurse = client_for(sandbox)
    assert nurse.get(note_path(sandbox, aid)).status_code == 200
    path = f"/v1/patients/{sandbox[1]}/sources/{source_id}/{operation}"
    headers = {"Idempotency-Key": str(uuid4())}
    importer = client_for(sandbox, "importer")
    response = (importer.put(path, json={"visibility": "patient_and_care_team"}, headers=headers)
                if operation == "visibility" else
                importer.post(path, json={"reason": "synthetic correction"}, headers=headers))
    assert response.status_code in (200, 202), response.text
    after = nurse.get(note_path(sandbox, aid))
    assert after.status_code == 409
    assert after.json()["error"]["code"] == "note_unavailable"
    assert "Poor intake" not in after.text


def test_assessment_without_sbar_is_unavailable(sandbox):
    seed_checks(sandbox, 6)
    result = store(sandbox, BASE)
    assert result.assessment["verdict"] == "within_normal"
    response = client_for(sandbox).get(note_path(sandbox, result.assessment["id"]))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "note_unavailable"


def test_superseded_source_and_revoked_access_never_return_old_note(sandbox):
    result, source_id = escalated(sandbox)
    route = note_path(sandbox, result.assessment["id"])
    nurse = client_for(sandbox)
    assert nurse.get(route).status_code == 200
    # A successor must retain the original document identity, not a random fixture ID.
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        original = conn.execute("SELECT payload FROM sources WHERE id=%s", (source_id,)).fetchone()["payload"]
    replacement = dict(original, external_version_id="2", supersedes_version_id=str(source_id))
    replacement["records"] = [dict(original["records"][0], value="Synthetic reassessment of intake.")]
    import_note(sandbox, replacement)
    response = nurse.get(route)
    assert response.status_code == 409 and "Poor intake" not in response.text
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("UPDATE assignments SET active=false WHERE patient_id=%s AND principal_id=%s",
                     (sandbox[1], sandbox[2]["nurse"].principal_id))
    response = nurse.get(route)
    assert response.status_code == 404 and "Poor intake" not in response.text


def test_foreign_tenant_cannot_export_an_existing_assessment(sandbox):
    result, _ = escalated(sandbox)
    identity = sandbox[2]["nurse"]
    from fastapi.testclient import TestClient

    from patient_memory.api import create_app
    from patient_memory.auth import Identity, synthetic_token
    tenant, actor = uuid4(), uuid4()
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("INSERT INTO tenants VALUES(%s,'synthetic-other')", (tenant,))
        conn.execute("INSERT INTO principals(id,tenant_id,name) VALUES(%s,%s,'synthetic-other')",
                     (actor, tenant))
    client = TestClient(create_app(sandbox[0], sandbox[3]))
    client.headers["Authorization"] = "Bearer " + synthetic_token(Identity(actor, tenant), sandbox[0])
    response = client.get(note_path(sandbox, result.assessment["id"]))
    assert response.status_code == 404 and "Poor intake" not in response.text
    assert tenant != identity.tenant_id
