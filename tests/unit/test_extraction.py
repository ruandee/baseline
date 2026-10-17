from patient_memory.domain import SourceInput, now
from patient_memory.extraction import extract


def note(text):
    return SourceInput(external_document_id="synthetic", external_version_id="1",
                       source_system="synthetic", kind="nursing_note", author_role="nurse",
                       recorded_at=now(), text=text)


def test_unicode_exact_spans_and_no_invented_clinical_fact():
    text, facts = extract(note("  No fever.\r\nFamily history of diabetes.\n😀 Patient says café helps."))
    assert len(facts) == 3
    assert all(text[c.start:c.end] == c.quote for c in facts)
    assert all(c.concept == "source_assertion" and c.polarity == "uncertain" for c in facts)
    assert all(c.valid_from is None for c in facts)


def test_structured_order_has_explicit_attribution():
    source = note("x").model_dump()
    source.update(kind="medication_event", author_role="system", text=None,
                  records=[{"concept": "synthetic-medication", "value": "x", "event_type": "stopped",
                            "order_id": "synthetic-order"}])
    text, facts = extract(SourceInput.model_validate(source))
    assert facts[0].event_type == "stopped"
    assert facts[0].order_id == "synthetic-order"
    assert text[facts[0].start:facts[0].end] == facts[0].quote
