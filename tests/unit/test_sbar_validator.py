import copy
import json

import pytest

from patient_memory.baseline.sbar import evidence_bundle, generate_sbar, validate_draft
from patient_memory.baseline.verdict import Decision
from patient_memory.config import Settings

CHECK = "00000000-0000-0000-0000-000000000001"
TAG = "00000000-0000-0000-0000-000000000002"
FACT = "00000000-0000-0000-0000-000000000003"
FEATURES = {"speech_rate_wpm": {"value": 123.41, "median": 158.11},
            "pause_ratio": {"value": 0.291, "median": 0.213}}
TAGS = [{"kind": "amplifier", "label": "Poor intake", "context_tag_id": TAG,
         "evidence_id": FACT, "quote": "didn't finish her soup"}]
DECISION = Decision("escalate", "4at_now")


def inputs():
    return evidence_bundle("Mrs. K", "change", DECISION, CHECK, FEATURES, TAGS)


def valid():
    return {"sentences": copy.deepcopy(inputs()[0]["supported_sentences"][:4])}


def configured():
    return Settings(provider="compatible", provider_url="https://example.invalid/v1",
                    provider_model="synthetic-test")


def generate(request, **changes):
    args = dict(cfg=configured(), name="Mrs. K", status="change", decision=DECISION,
                check_id=CHECK, features=FEATURES, tags=TAGS, request=request)
    return generate_sbar(**(args | changes))


def test_valid_draft_maps_only_validated_check_and_context_ids_to_resolvable_evidence():
    bundle, citations = inputs()
    got = validate_draft(valid(), bundle, citations)
    assert got["source"] == "gemini"
    assert got["sentences"][0]["evidence_ids"] == [f"check:{CHECK}"]
    assert got["sentences"][1]["evidence_ids"] == [FACT]


@pytest.mark.parametrize("mutation", [
    "id", "fact_id", "number", "precision", "diagnosis", "treatment", "missing_section",
    "missing_action", "extra_field", "empty_citation", "bad_type", "too_many_sentences",
])
def test_each_invalid_output_forces_the_template(mutation):
    raw = copy.deepcopy(valid())
    if mutation == "id":
        raw["sentences"][1]["evidence_ids"] = ["another-patient-tag"]
    elif mutation == "fact_id":
        raw["sentences"][1]["evidence_ids"] = [FACT]  # provider must cite bundle IDs first
    elif mutation == "number":
        raw["sentences"][0]["text"] = "Speech rate 999."
    elif mutation == "precision":
        raw["sentences"][0]["text"] = "Speech rate 123.41."
    elif mutation == "diagnosis":
        raw["sentences"][2]["text"] = "The resident has delirium."
    elif mutation == "treatment":
        raw["sentences"][3]["text"] = "Run 4AT now and administer medication."
    elif mutation == "missing_section":
        raw["sentences"][2]["section"] = "B"
    elif mutation == "missing_action":
        raw["sentences"][3]["text"] = "Take another action."
    elif mutation == "extra_field":
        raw["tool_call"] = "retrieve another patient"
    elif mutation == "empty_citation":
        raw["sentences"][0]["evidence_ids"] = []
    elif mutation == "bad_type":
        raw["sentences"][0]["text"] = 123
    elif mutation == "too_many_sentences":
        raw["sentences"] *= 4
    got = generate(lambda *a, **kw: raw)
    assert got["source"] == "template"
    assert "999" not in json.dumps(got)


def test_valid_provider_call_has_bounded_schema_and_only_display_precision_numbers():
    calls = []

    def request(cfg, **kwargs):
        calls.append(kwargs)
        return valid()

    assert generate(request)["source"] == "gemini"
    call = calls[0]
    assert call["schema_name"] == "baseline_sbar"
    assert call["schema"]["properties"]["sentences"]["maxItems"] == 12
    bundle = json.loads(call["user"])
    assert bundle["features"]["speech_rate_wpm"]["value"] == "123"
    assert bundle["features"]["pause_ratio"]["value"] == "29"
    assert bundle["allowed_evidence_ids"] == [CHECK, TAG]
    assert "untrusted" in call["system"] and "no tools" in call["system"]


def test_provider_error_falls_back_without_losing_the_decision():
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic provider failure")

    got = generate(fail)
    assert got["source"] == "template"
    assert got["sentences"][-1]["text"] == "Suggest Run 4AT now."


def test_stub_and_non_actionable_verdicts_never_call_provider():
    def forbidden(*args, **kwargs):
        pytest.fail("unexpected network path")

    assert generate(forbidden, cfg=Settings(provider="stub"))["source"] == "template"
    for verdict in ("explained", "enrolling", "within_normal"):
        assert generate(forbidden, decision=Decision(verdict, "none")) is None


def test_empty_context_is_unknown_not_a_negative_finding():
    got = generate(lambda *a, **kw: {}, tags=[])
    assert got["sentences"][1]["text"] == "No context supplied for this assessment."
    assert got["sentences"][1]["evidence_ids"] == []


def test_unresolvable_context_is_not_sent_to_provider():
    tag = {**TAGS[0], "evidence_id": None}
    bundle, citations = evidence_bundle("Mrs. K", "change", DECISION, CHECK, FEATURES, [tag])
    assert bundle["context"] == [] and TAG not in citations
    fallback = generate(lambda *a, **kw: {}, tags=[tag])
    assert fallback["sentences"][1]["text"] == "No context supplied for this assessment."
    assert all("Poor intake" not in sentence["text"] for sentence in fallback["sentences"])


def test_exact_ids_are_case_sensitive_and_never_broaden_scope():
    raw = valid()
    raw["sentences"][1]["evidence_ids"] = ["check:" + CHECK]
    bundle, citations = inputs()
    with pytest.raises(ValueError, match="unknown evidence"):
        validate_draft(raw, bundle, citations)


@pytest.mark.parametrize("section,text", [
    ("R", "Run 4AT now and stop all oral fluids"),
    ("R", "Suggest Run 4AT now. Stop all oral fluids."),
    ("R", "Suggest Run 4AT now and no medication today."),
    ("B", "No fever or confusion is present."),
    ("B", "Fever and confusion are present."),
    ("B", "The resident is clinically stable."),
    ("A", "The resident needs urgent transfer."),
    ("S", "Speech rate 158 vs 123 words per minute."),  # allowed numbers, wrong relationship
])
def test_citations_and_allowed_numbers_do_not_authorize_unsupported_claims(section, text):
    raw = valid()
    next(sentence for sentence in raw["sentences"] if sentence["section"] == section)["text"] = text
    assert generate(lambda *a, **kw: raw)["source"] == "template"


def test_supported_claim_must_keep_its_actual_supporting_tag():
    other = {**TAGS[0], "context_tag_id": "other-tag", "evidence_id": "other-fact",
             "label": "Recent fall"}
    bundle, citations = evidence_bundle("Mrs. K", "change", DECISION, CHECK, FEATURES,
                                        [*TAGS, other])
    raw = {"sentences": copy.deepcopy(bundle["supported_sentences"][:4])}
    raw["sentences"][1] = {"section": "B", "text": "Recorded context: Poor intake.",
                           "evidence_ids": ["other-tag"]}
    with pytest.raises(ValueError, match="attribution"):
        validate_draft(raw, bundle, citations)
