"""Real RR + raw speech provenance through preliminary export and current nurse readback."""
import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.baseline.note import CHECK_SYSTEM, SIGNAL_SYSTEM, validate_document_reference
from tests.contract.test_api import client_for, import_note
from tests.contract.test_context import post as post_context
from tests.contract.test_motion import capture, grant
from tests.integration.test_note_export import note_path
from tests.integration.test_vitals_signal import example, overview, rr_payload
from tests.js_runner import run_js_suites


def test_multimodal_note_cites_actual_current_and_baseline_sources_without_model(sandbox, monkeypatch, tmp_path):
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
    fixture = tmp_path / "multimodal.json"
    fixture.write_text(json.dumps({"overview": page}), encoding="utf-8")
    run_js_suites("multimodal_sbar.test.js", fixture_env={"MULTIMODAL_FIXTURE": str(fixture)})
    for role in ("patient", "psw", "admin"):
        assert client_for(sandbox, role).get(note_path(sandbox, latest["id"])).status_code == 404


def test_rr_only_draft_never_uses_voice_primary_or_invents_missing_hr(sandbox):
    import_note(sandbox, rr_payload(datetime.now(UTC)))
    latest = overview(sandbox)["latest_assessment"]
    assert latest["sbar"] and latest["check"] is None
    text = " ".join(s["text"] for s in latest["sbar"]["sentences"])
    assert "breaths/min" in text and "speech" not in text.lower() and "heart" not in text.lower()
    assert client_for(sandbox).get(note_path(sandbox, latest["id"])).status_code == 200


@pytest.mark.parametrize("with_vitals", [False, True])
def test_motion_template_and_motion_vitals_corroboration_without_speech(sandbox, with_vitals):
    grant(sandbox)
    for _ in range(3):
        result = capture(sandbox, is_baseline=True)
        assert result.status_code == 200, result.text
    changed = {"sit_to_stand_s": 2.5, "trunk_sway": .12, "step_cadence_spm": 45}
    assert capture(sandbox, features=changed).status_code == 200
    result = capture(sandbox, features=changed)
    assert result.status_code == 200, result.text
    if with_vitals:
        import_note(sandbox, rr_payload(datetime.now(UTC)))
    latest = overview(sandbox)["latest_assessment"]
    assert latest["sbar"] and latest["check"] is None
    text = " ".join(s["text"] for s in latest["sbar"]["sentences"])
    assert "Time to half-rise 2.50 vs baseline median 1.20 s" in text
    assert "client-derived, unverified" in text
    assert "speech" not in text.lower()
    assert latest["corroborated"] is with_vitals
    if with_vitals:
        assert "26.00 vs baseline median 16.00 breaths/min" in text
        assert latest["modalities"]["motion"]["params"]["projection"] == "immutable_capture_current_revision"
    note = client_for(sandbox).get(note_path(sandbox, latest["id"]))
    assert note.status_code == 200, note.text
    assert validate_document_reference(note.json()) == []
    assert not latest.get("cited_checks")


@pytest.mark.parametrize("damage", ["expired", "foreign_check", "revoked"])
def test_export_and_overview_revalidate_expiry_capture_scope_and_assignment(sandbox, damage):
    example(sandbox)
    latest = overview(sandbox)["latest_assessment"]
    cfg, pid, actors, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as conn:
        if damage == "expired":
            eid = latest["modalities"]["vitals"]["evidence_ids"][0]
            conn.execute("UPDATE facts SET valid_to=valid_from+interval '1 microsecond' WHERE id=%s", (eid,))
            expired = conn.execute("SELECT valid_from<valid_to AND valid_to<clock_timestamp() FROM facts WHERE id=%s",
                                   (eid,)).fetchone()[0]
            assert expired  # preserve the actual event and the storage interval invariant
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


def test_context_expiry_and_source_retraction_remove_multimodal_draft(sandbox):
    context = post_context(sandbox, {"kind": "amplifier", "tag": "poor_intake",
        "label": "Synthetic poor intake", "valid_from": (datetime.now(UTC)-timedelta(hours=1)).isoformat(),
        "valid_to": (datetime.now(UTC)+timedelta(hours=1)).isoformat()})
    assert context.status_code == 201
    imported = example(sandbox)
    latest = overview(sandbox)["latest_assessment"]
    assert latest["sbar"]
    note = note_path(sandbox, latest["id"])
    assert client_for(sandbox).get(note).status_code == 200
    with psycopg.connect(sandbox[0].admin_database_url) as conn:
        conn.execute("UPDATE context_tags SET valid_to=%s WHERE patient_id=%s AND id=%s",
                     (datetime.now(UTC)-timedelta(seconds=1), sandbox[1], context.json()["id"]))
    assert client_for(sandbox).get(note).status_code == 409
    assert overview(sandbox)["latest_assessment"]["sbar"] is None
    response = client_for(sandbox, "importer").post(
        f"/v1/patients/{sandbox[1]}/sources/{imported['source_version_id']}/retract",
        json={"reason": "Synthetic correction"}, headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 200
    assert client_for(sandbox).get(note).status_code == 409
    assert overview(sandbox)["latest_assessment"] is None
