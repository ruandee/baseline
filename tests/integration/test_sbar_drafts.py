"""Configured providers remain mocked; exercise persisted drafts and scoped evidence reads."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.contract.test_api import client_for
from tests.contract.test_context import post as post_context
from tests.integration.test_assessments import SLOW, seed_checks, store


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
    nurse = client_for(sandbox, "nurse")
    page = nurse.get(f"/v1/patients/{sandbox[1]}/overview").json()
    draft = page["latest_assessment"]["sbar"]
    assert draft["source"] == ("template" if invalid else "gemini")
    assert len(calls) == 1
    fact_id = draft["sentences"][1]["evidence_ids"][0]
    assert nurse.get(f"/v1/patients/{sandbox[1]}/evidence/{fact_id}").status_code == 200
    assert client_for(sandbox, "patient").get(
        f"/v1/patients/{sandbox[1]}/overview").status_code == 404
