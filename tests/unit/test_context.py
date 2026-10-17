from datetime import datetime, timedelta, timezone

from patient_memory.baseline.context import structured_tags
from patient_memory.domain import SourceInput
from patient_memory.extraction import extract

RECORDED = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


def tags_for(kind, *records, effective_from=None):
    source = SourceInput.model_validate({
        "external_document_id": "synthetic-doc", "external_version_id": "1",
        "source_system": "synthetic", "kind": kind,
        "author_role": "system", "recorded_at": RECORDED, "records": list(records),
        "effective_from": effective_from})
    canonical, candidates = extract(source)
    return canonical, structured_tags(source, candidates)


def med(drug, event_type="ordered", **extra):
    return {"concept": "medication", "value": drug, "event_type": event_type,
            "order_id": "synthetic-order", **extra}


def test_high_risk_medication_order_becomes_amplifier_quoting_the_record():
    canonical, tags = tags_for("medication_event", med("oxybutynin 5 mg"))
    (tag,) = tags
    assert (tag.kind, tag.tag) == ("amplifier", "high_risk_med_new")
    assert canonical[tag.start:tag.end] == tag.quote
    assert "oxybutynin" in tag.quote
    assert tag.valid_from == RECORDED
    assert tag.valid_to == RECORDED + timedelta(days=7)


def test_only_orders_and_administrations_of_listed_drugs_count():
    for event_type in ("stopped", "mentioned"):
        extra = {"order_id": "o-1"} if event_type == "stopped" else {}
        assert tags_for("medication_event", med("oxybutynin", event_type, **extra))[1] == []
    assert tags_for("medication_event", med("paracetamol 500 mg"))[1] == []
    assert len(tags_for("medication_event", med("Lorazepam 0.5 mg", "administered"))[1]) == 1


def test_absent_or_uncertain_records_never_make_tags():
    for polarity in ("absent", "uncertain"):
        assert tags_for("medication_event", med("oxybutynin", polarity=polarity))[1] == []
        assert tags_for("observation", {"concept": "context.exertion", "value": "Marathon",
                                        "polarity": polarity})[1] == []


def test_medication_and_fever_windows_ignore_a_longer_record_window():
    end = (RECORDED + timedelta(days=60)).isoformat()
    _, (drug,) = tags_for("medication_event", med("oxybutynin", effective_to=end))
    assert drug.valid_to == RECORDED + timedelta(days=7)
    _, (fever,) = tags_for("observation", {"concept": "temperature_c", "value": 39.0,
                                           "effective_to": end})
    assert fever.valid_to == RECORDED + timedelta(hours=48)


def temperature(value, **extra):
    return {"concept": "temperature_c", "value": value, **extra}


def test_temperature_at_or_above_37_8_is_a_fever_amplifier_for_48_hours():
    canonical, tags = tags_for("observation", temperature(37.8))
    (tag,) = tags
    assert (tag.kind, tag.tag) == ("amplifier", "fever_documented")
    assert canonical[tag.start:tag.end] == tag.quote == "temperature_c: 37.8 [polarity=present]"
    assert tag.valid_to - tag.valid_from == timedelta(hours=48)


def test_context_observation_becomes_the_matching_tag_within_its_recorded_window():
    end = RECORDED + timedelta(hours=6)
    canonical, tags = tags_for("observation", {
        "concept": "context.exertion", "value": "Running the Toronto marathon",
        "effective_from": RECORDED.isoformat(), "effective_to": end.isoformat()})
    (tag,) = tags
    assert (tag.kind, tag.tag) == ("explainer", "exertion")
    assert canonical[tag.start:tag.end] == tag.quote
    assert "Toronto marathon" in tag.quote
    assert (tag.valid_from, tag.valid_to) == (RECORDED, end)


def test_context_observation_without_window_uses_taxonomy_default():
    _, (dentures,) = tags_for("observation", {"concept": "context.dentures", "value": "New dentures"})
    assert dentures.valid_to == RECORDED + timedelta(days=7)
    _, (exertion,) = tags_for("observation", {"concept": "context.exertion", "value": "Marathon"})
    assert exertion.valid_to is None


def test_unknown_context_tag_makes_no_tag():
    assert tags_for("observation", {"concept": "context.astrology", "value": "x"})[1] == []


def test_language_change_cannot_create_a_resident_wide_explainer():
    for window in ({}, {"effective_to": (RECORDED + timedelta(hours=1)).isoformat()}):
        assert tags_for("observation", {
            "concept": "context.language_change", "value": "French prompt", **window})[1] == []


def test_temperature_below_threshold_or_not_a_number_makes_no_tag():
    assert tags_for("observation", temperature(37.7))[1] == []
    assert tags_for("observation", temperature("37.9 approx"))[1] == []
    assert tags_for("observation", temperature(38.5, polarity="absent"))[1] == []
