"""Real RR + raw speech provenance through preliminary export and current nurse readback."""
import base64
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.baseline.note import CHECK_SYSTEM, SIGNAL_SYSTEM, validate_document_reference
from tests.contract.test_api import client_for, import_note
from tests.integration.test_note_export import note_path
from tests.integration.test_vitals_signal import example, overview, rr_payload


def test_multimodal_note_cites_actual_current_and_baseline_sources_without_model(sandbox, monkeypatch):
    monkeypatch.setattr("patient_memory.baseline.llm.request_json",
                        lambda *a, **k: pytest.fail("multimodal drafts never call a provider"))
    example(sandbox)
    page = overview(sandbox)
    latest = page["latest_assessment"]
    assert latest["sbar"] and latest["draft_status"] == "multimodal_template"
    nurse = client_for(sandbox)
    response = nurse.get(note_path(sandbox, latest["id"]))
    assert response.status_code == 200, response.text
    document = response.json()
    assert validate_document_reference(document) == []
    text = base64.b64decode(document["content"][0]["attachment"]["data"]).decode()
    assert "26.00 vs baseline median 16.00 breaths/min" in text
    assert "vitals: change" in text and "speech: provisional" in text
    assert "Resting heart" not in text and "No context supplied" in text
    checks = {r["identifier"]["value"] for r in document["context"]["related"]
              if r["identifier"]["system"] == CHECK_SYSTEM}
    assert len(checks) == 7 and checks == set(latest["cited_checks"])
    primary = next(e for e in document["extension"] if e["url"].endswith("assessment-provenance"))
    assert next(e for e in primary["extension"] if e["url"] == "check")["valueIdentifier"]["system"] == SIGNAL_SYSTEM
    for sentence in latest["sbar"]["sentences"]:
        for eid in sentence["evidence_ids"]:
            if not eid.startswith("check:"):
                assert nurse.get(f"/v1/patients/{sandbox[1]}/evidence/{eid}").status_code == 200
    for role in ("patient", "psw", "admin"):
        assert client_for(sandbox, role).get(note_path(sandbox, latest["id"])).status_code == 404


def test_rr_only_draft_never_uses_voice_primary_or_invents_missing_hr(sandbox):
    import_note(sandbox, rr_payload(datetime.now(UTC)))
    latest = overview(sandbox)["latest_assessment"]
    assert latest["sbar"] and latest["check"] is None
    text = " ".join(s["text"] for s in latest["sbar"]["sentences"])
    assert "breaths/min" in text and "speech" not in text.lower() and "heart" not in text.lower()
    assert client_for(sandbox).get(note_path(sandbox, latest["id"])).status_code == 200


@pytest.mark.parametrize("damage", ["expired", "foreign_check", "revoked"])
def test_export_and_overview_revalidate_expiry_capture_scope_and_assignment(sandbox, damage):
    example(sandbox)
    latest = overview(sandbox)["latest_assessment"]
    cfg, pid, actors, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        if damage == "expired":
            eid = latest["modalities"]["vitals"]["evidence_ids"][0]
            conn.execute("UPDATE facts SET valid_to=%s WHERE id=%s", (datetime.now(UTC)-timedelta(seconds=1), eid))
        elif damage == "foreign_check":
            draft = latest["sbar"]
            draft["sentences"][0]["evidence_ids"].append("check:"+str(uuid4()))
            conn.execute("UPDATE assessments SET sbar=%s WHERE id=%s", (Jsonb(draft), latest["id"]))
        else:
            conn.execute("UPDATE assignments SET active=false WHERE patient_id=%s AND principal_id=%s",
                         (pid, actors["nurse"].principal_id))
    nurse = client_for(sandbox)
    assert nurse.get(note_path(sandbox, latest["id"])).status_code == (404 if damage == "revoked" else 409)
    response = nurse.get(f"/v1/patients/{pid}/overview")
    if damage == "revoked":
        assert response.status_code == 404
    else:
        current = response.json()["latest_assessment"]
        assert current["sbar"] is None and "cited_checks" not in current
        assert current["draft_status"] == "unavailable_multimodal_evidence"
