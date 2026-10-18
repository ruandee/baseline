"""BL-33: the draft note is a pure, exact FHIR R4 DocumentReference projection of a stored SBAR."""
import base64
import copy
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from patient_memory.baseline.note import (
    CHECK_SYSTEM,
    FACT_SYSTEM,
    NOTE_TYPE_TEXT,
    StoredSbar,
    build_document_reference,
    note_text,
    validate_baseline_profile,
    validate_document_reference,
)
from patient_memory.errors import Problem

CHECK, FACT = str(uuid4()), str(uuid4())


def stored(source="template", fact=FACT):
    return {"source": source, "sentences": [
        {"section": "S", "text": "Zoë's speech differs from their usual: speech rate 123 vs 158 "
                                 "words per minute, pauses 29% vs 21%.",
         "evidence_ids": [f"check:{CHECK}"]},
        {"section": "B", "text": "Poor intake <b>&amp</b>.", "evidence_ids": [fact]},
        {"section": "A", "text": "Meets the change threshold; Poor intake present.",
         "evidence_ids": [f"check:{CHECK}", fact]},
        {"section": "R", "text": "Suggest Run 4AT now.", "evidence_ids": [f"check:{CHECK}"]},
    ]}


def row(**overrides):
    base = {"id": uuid4(), "patient_id": uuid4(), "check_id": CHECK, "external_id": "synthetic-k",
            "created_at": datetime(2026, 10, 17, 9, 30, 1, 250000, tzinfo=UTC),
            "check_ts": datetime(2026, 10, 17, 9, 29, tzinfo=UTC), "change_status": "change",
            "verdict": "escalate", "suggested_action": "4at_now",
            "params": {"source_revision": 7}}
    return {**base, **overrides}


def build(sbar=None, **overrides):
    raw = sbar or stored()
    return build_document_reference(row(**overrides), StoredSbar.model_validate(raw)), raw


def test_payload_validates_and_is_an_unsigned_preliminary_draft():
    note, _ = build()
    assert validate_document_reference(note) == []
    assert validate_baseline_profile(note) == []
    assert note["resourceType"] == "DocumentReference"
    assert (note["status"], note["docStatus"]) == ("current", "preliminary")
    assert note["type"] == {"text": NOTE_TYPE_TEXT}
    assert "authenticator" not in note
    assert any(t["code"] == "synthetic" for t in note["meta"]["tag"])


def test_attachment_carries_the_exact_stored_text_in_stored_order():
    note, raw = build()
    attachment = note["content"][0]["attachment"]
    text = base64.b64decode(attachment["data"]).decode("utf-8")
    assert text == "\n".join(f"{s['section']}: {s['text']}" for s in raw["sentences"])
    assert attachment["size"] == len(text.encode("utf-8"))
    sentences = [e for e in note["extension"] if e["url"].endswith("/sbar-sentence")]
    assert [s["extension"][1]["valueString"] for s in sentences] == [
        s["text"] for s in raw["sentences"]]
    # Narrative is escaped; the attachment keeps the stored characters untouched.
    assert "&lt;b&gt;&amp;amp&lt;/b&gt;" in note["text"]["div"] and "<b>&amp</b>" in text


def test_provenance_subject_author_and_dates_are_preserved():
    r = row()
    note = build_document_reference(r, StoredSbar.model_validate(stored("gemini")))
    assert note["subject"]["reference"] == f"Patient/{r['patient_id']}"
    assert note["subject"]["display"] == "synthetic-k"
    assert note["date"] == "2026-10-17T09:30:01.250000+00:00"
    assert note["content"][0]["attachment"]["creation"] == note["date"]
    assert note["context"]["period"]["start"] == "2026-10-17T09:29:00+00:00"
    assert "configured model" in note["author"][0]["display"]
    ext = {e["url"].rsplit("/", 1)[1]: e for e in note["extension"]}
    assert ext["sbar-source"]["valueCode"] == "gemini"
    provenance = {e["url"]: e for e in ext["assessment-provenance"]["extension"]}
    assert provenance["sourceRevision"]["valueInteger"] == 7
    assert provenance["assessment"]["valueIdentifier"]["value"] == str(r["id"])
    assert provenance["check"]["valueIdentifier"] == {"system": CHECK_SYSTEM, "value": CHECK}


def test_check_and_fact_citations_use_distinct_identifier_systems():
    note, _ = build()
    related = note["context"]["related"]
    assert related == [
        {"type": "Observation", "identifier": {"system": CHECK_SYSTEM, "value": CHECK},
         "display": "Voice check (signal data)"},
        {"identifier": {"system": FACT_SYSTEM, "value": FACT}, "display": "Source evidence fact"},
    ]
    # No check: prefix ever reaches a fact identifier (the /evidence endpoint is fact-only).
    facts = [r["identifier"]["value"] for r in related if r["identifier"]["system"] == FACT_SYSTEM]
    assert all(not f.startswith("check:") for f in facts)


@pytest.mark.parametrize("bad", ["check:" + str(uuid4()), "not-an-id"])
def test_foreign_check_or_malformed_citation_is_unavailable(bad):
    with pytest.raises(Problem) as err:
        build(stored(fact=bad))
    assert (err.value.status, err.value.code) == (409, "note_unavailable")


def test_builder_never_calls_a_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("model called")
    monkeypatch.setattr("patient_memory.baseline.llm.request_json", boom)
    build()


def test_note_text_is_verbatim():
    sbar = StoredSbar.model_validate(stored())
    assert note_text(sbar).splitlines()[3] == "R: Suggest Run 4AT now."


@pytest.mark.parametrize("mutate, message", [
    (lambda n: n.update(status="draft"), "status"),
    (lambda n: n.pop("status"), "status"),
    (lambda n: n.update(docStatus="pending"), "docStatus"),
    (lambda n: n.update(content=[]), "content"),
    (lambda n: n["content"][0].pop("attachment"), "attachment"),
    (lambda n: n["content"][0]["attachment"].update(data="not base64!"), "data"),
    (lambda n: n["content"][0]["attachment"].pop("contentType"), "contentType"),
    (lambda n: n["content"][0]["attachment"].update(size=-1), "size"),
    (lambda n: n.update(date="2026-10-17"), "date"),
    (lambda n: n.update(resourceType="Composition"), "resourceType"),
    (lambda n: n.update(signedBy="x"), "unknown element"),
    (lambda n: n.update(description=None), "empty"),
    (lambda n: n["extension"].append({"url": "u", "valueString": "a", "extension": [
        {"url": "x", "valueString": "b"}]}), "exactly one"),
    (lambda n: n["extension"].append({"url": "u"}), "exactly one"),
    (lambda n: n["subject"].update(reference=5), "subject.reference"),
    (lambda n: n["text"].update(div="<p>x</p>"), "text.div"),
    (lambda n: n.update(id="has space"), "id"),
])
def test_validator_rejects_r4_shape_violations(mutate, message):
    note, _ = build()
    broken = copy.deepcopy(note)
    mutate(broken)
    errors = validate_document_reference(broken)
    assert any(message in e for e in errors), errors


@pytest.mark.parametrize("mutate", [
    lambda n: n.update(docStatus="final"),
    lambda n: n.update(authenticator={"display": "Dr Synthetic"}),
    lambda n: n.update(type={"text": "Progress note"}),
    lambda n: n["content"][0]["attachment"].update(size=1),
])
def test_profile_rejects_signed_final_or_altered_drafts(mutate):
    note, _ = build()
    broken = copy.deepcopy(note)
    mutate(broken)
    assert validate_baseline_profile(broken)


def test_profile_detects_rewritten_text():
    note, raw = build()
    assert validate_baseline_profile(note, note_text(StoredSbar.model_validate(raw))) == []
    assert validate_baseline_profile(note, "S: paraphrased")
