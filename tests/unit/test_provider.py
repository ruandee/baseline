import json
from uuid import uuid4

import httpx
import pytest

from patient_memory.config import Settings
from patient_memory.domain import SourceInput, now
from patient_memory.errors import Problem
from patient_memory.extraction import extract, fact_id
from patient_memory.generation import build_answer
from patient_memory.providers import CompatibleSelector


def sample_fact():
    source = SourceInput(external_document_id="synthetic", external_version_id="1",
                         source_system="synthetic", kind="nursing_note", author_role="nurse",
                         recorded_at=now(), text="Sleep improved.")
    text, candidates = extract(source)
    c, sid = candidates[0], uuid4()
    return {"id": fact_id(sid, c), "source_id": sid, "payload": source.model_dump(mode="json"),
            "quote": c.quote, "start_offset": c.start, "end_offset": c.end,
            "concept": c.concept, "value": c.value, "polarity": c.polarity,
            "valid_from": None, "valid_to": None, "order_id": None, "event_type": None,
            "canonical_text": text, "recorded_at": now(), "ingested_at": now()}


def selector(handler):
    cfg = Settings(provider="compatible", provider_url="http://localhost:11434/v1", provider_model="synthetic-test-model")
    return CompatibleSelector(cfg, httpx.MockTransport(handler))


def test_optional_provider_can_only_select_valid_evidence():
    fact = sample_fact()

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert "tools" not in body
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"evidence_ids": [str(fact["id"])]})}}]})

    claims = selector(handler).generate("sleep", [fact], now())
    assert claims[0].text == fact["quote"]


def test_provider_fabrication_retries_twice_then_fails():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": json.dumps({"evidence_ids": [str(uuid4())]})}}]})

    with pytest.raises(Problem) as err:
        build_answer(selector(handler), "sleep", [sample_fact()],
                     {"index_complete": True, "truncated": False}, uuid4(), 1, now(), now())
    assert err.value.status == 502 and len(calls) == 2


def test_provider_timeout_is_not_missing_evidence():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)
    with pytest.raises(Problem) as err:
        selector(handler).generate("sleep", [sample_fact()], now())
    assert err.value.status == 504


def test_provider_http_errors_and_bad_json():
    with pytest.raises(Problem) as err:
        selector(lambda r: httpx.Response(503)).generate("sleep", [sample_fact()], now())
    assert err.value.status == 503
    with pytest.raises(ValueError):
        selector(lambda r: httpx.Response(200, content=b"not-json")).generate("sleep", [sample_fact()], now())


def test_model_abstention_does_not_claim_documentation_is_missing():
    model = selector(lambda r: httpx.Response(200, json={"choices": [{"message": {
        "content": '{"evidence_ids": []}'}}]}))
    answer = build_answer(model, "sleep", [sample_fact()],
                          {"index_complete": True, "truncated": False}, uuid4(), 1, now(), now())
    assert answer.status == "insufficient_evidence"
    assert answer.unknowns[0].reason == "selection_abstained"
    assert answer.evidence
