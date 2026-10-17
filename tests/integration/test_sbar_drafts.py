"""Configured providers remain mocked; exercise persisted drafts and scoped evidence reads."""
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from patient_memory.baseline.assess import lock_assessment
from patient_memory.baseline.sbar import enrich_assessment_sbar
from patient_memory.errors import Problem
from patient_memory.ingestion import bump
from patient_memory.lifecycle import assign, change_source
from patient_memory.speech.pipeline import Analysis
from patient_memory.storage import transaction
from tests.contract.test_api import client_for
from tests.contract.test_context import post as post_context
from tests.integration.test_assessments import QUALITY, SLOW, seed_checks, store


@pytest.mark.parametrize("invalid", [False, True])
def test_provider_draft_is_validated_persisted_and_read_with_scoped_citations(
        sandbox, monkeypatch, invalid):
    seed_checks(sandbox, 6)
    assert post_context(sandbox, {
        "kind": "amplifier", "tag": "poor_intake", "label": "Poor intake",
        "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }).status_code == 201
    calls = []

    def request(cfg, **kwargs):
        bundle = json.loads(kwargs["user"])
        calls.append(bundle)
        sentences = bundle["supported_sentences"][:4]
        if invalid:
            sentences[1]["evidence_ids"] = ["invented-tag"]
        return {"sentences": sentences}

    monkeypatch.setattr("patient_memory.baseline.llm.request_json", request)
    cfg = sandbox[0].model_copy(update={"provider": "compatible"})
    configured = (cfg, *sandbox[1:])
    result = store(configured, SLOW)
    assert result.assessment["verdict"] == "escalate"
    enrich_assessment_sbar(cfg, sandbox[2]["nurse"], sandbox[1], result.assessment["id"])
    nurse = client_for(sandbox, "nurse")
    page = nurse.get(f"/v1/patients/{sandbox[1]}/overview").json()
    draft = page["latest_assessment"]["sbar"]
    assert draft["source"] == ("template" if invalid else "gemini")
    assert len(calls) == 1
    fact_id = draft["sentences"][1]["evidence_ids"][0]
    assert nurse.get(f"/v1/patients/{sandbox[1]}/evidence/{fact_id}").status_code == 200
    assert client_for(sandbox, "patient").get(
        f"/v1/patients/{sandbox[1]}/overview").status_code == 404


def test_upload_commits_admission_and_releases_both_locks_before_provider(sandbox, monkeypatch):
    seed_checks(sandbox, 6)
    cfg, pid, actors, objects = sandbox
    assert post_context(sandbox, {
        "kind": "amplifier", "tag": "poor_intake", "label": "Poor intake",
        "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    }).status_code == 201
    calls = []

    def request(*args, **kwargs):
        # Another ordinary connection can acquire tenant + patient admission while drafting.
        # The check/template must already be committed and visible, not merely staged.
        with transaction(cfg, actors["nurse"]) as conn:
            conn.execute("SET LOCAL lock_timeout='250ms'")
            lock_assessment(conn, actors["nurse"].tenant_id, pid)
            row = conn.execute("SELECT sbar FROM assessments WHERE patient_id=%s",
                               (pid,)).fetchone()
            assert row["sbar"]["source"] == "template"
        bundle = json.loads(kwargs["user"])
        calls.append(bundle)
        return {"sentences": bundle["supported_sentences"][:4]}

    monkeypatch.setattr("patient_memory.baseline.llm.request_json", request)
    monkeypatch.setattr("patient_memory.api.analyze", lambda *args: Analysis(
        True, QUALITY, SLOW, [], [], {}))
    configured = (cfg.model_copy(update={"provider": "compatible"}), pid, actors, objects)
    response = client_for(configured, "nurse").post(
        f"/v1/patients/{pid}/checks", data={"mode": "resident", "device_id": "tablet-1"},
        files={"audio": ("synthetic.wav", b"synthetic stub", "audio/wav")})
    assert response.status_code == 200, response.text
    assert response.json()["assessment"]["verdict"] == "escalate"
    assert len(calls) == 1
    page = client_for(sandbox).get(f"/v1/patients/{pid}/overview").json()
    assert page["latest_assessment"]["sbar"]["source"] == "gemini"


@pytest.mark.parametrize("mutation", ["retract", "purge", "revision", "permission"])
def test_changed_source_or_permission_discards_postcommit_draft(sandbox, monkeypatch, mutation):
    seed_checks(sandbox, 6)
    cfg, pid, actors, _ = sandbox
    response = post_context(sandbox, {
        "kind": "amplifier", "tag": "poor_intake", "label": "synthetic source quote",
        "valid_from": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    })
    assert response.status_code == 201, response.text
    source_id = response.json()["source_id"]
    result = store(sandbox, SLOW)

    def request(*args, **kwargs):
        actor = actors["admin"] if mutation == "permission" else actors["importer"]
        with transaction(cfg, actor) as conn:
            conn.execute("SET LOCAL lock_timeout='250ms'")
            if mutation == "permission":
                from patient_memory.domain import AssignmentInput
                assign(conn, actor, pid, AssignmentInput(
                    principal_id=actors["nurse"].principal_id, role="nurse", active=False), uuid4())
            elif mutation == "revision":
                lock_assessment(conn, actors["importer"].tenant_id, pid)
                bump(conn, pid)
            else:
                change_source(conn, actor, pid, source_id, mutation, str(uuid4()),
                              {"reason": "synthetic concurrent change"}, uuid4())
        bundle = json.loads(kwargs["user"])
        return {"sentences": bundle["supported_sentences"][:4]}

    monkeypatch.setattr("patient_memory.baseline.llm.request_json", request)
    configured = cfg.model_copy(update={"provider": "compatible"})
    with pytest.raises(Problem) as discarded:
        enrich_assessment_sbar(configured, actors["nurse"], pid, result.assessment["id"])
    assert discarded.value.status == (404 if mutation == "permission" else 409)
    with transaction(cfg, actors["importer"]) as conn:
        row = conn.execute("SELECT sbar FROM assessments WHERE id=%s",
                           (result.assessment["id"],)).fetchone()
        # A grant change leaves only the original safe template; source mutation scrubs it.
        assert row["sbar"] is None if mutation != "permission" else row["sbar"]["source"] == "template"
        assert conn.execute("SELECT count(*) AS n FROM voice_checks WHERE patient_id=%s",
                            (pid,)).fetchone()["n"] == 7
