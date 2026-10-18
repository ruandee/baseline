from datetime import timedelta
from uuid import uuid4

import psycopg

from patient_memory.domain import SourceInput, now
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from patient_memory.worker import run_once


def publish(sandbox, kind, record):
    cfg, pid, actors, objects = sandbox
    source = SourceInput.model_validate({
        "external_document_id": f"synthetic-{uuid4()}", "external_version_id": "1",
        "source_system": "synthetic", "kind": kind, "author_role": "system",
        "recorded_at": now(), "records": [record]})
    with transaction(cfg, actors["importer"]) as conn:
        result = submit(conn, actors["importer"], pid, source, str(uuid4()), objects)
    assert run_once(cfg, actors["importer"], objects)
    return result["source_version_id"]


def tags_of(sandbox, source_id):
    cfg, pid, actors, _ = sandbox
    with transaction(cfg, actors["nurse"]) as conn:
        source = conn.execute("SELECT canonical_text FROM sources WHERE id=%s", (source_id,)).fetchone()
        tags = conn.execute("SELECT * FROM context_tags WHERE source_id=%s", (source_id,)).fetchall()
        facts = {f["id"]: f for f in conn.execute("SELECT * FROM facts WHERE source_id=%s", (source_id,))}
    return source["canonical_text"], tags, facts


def test_oxybutynin_order_creates_high_risk_tag_with_valid_quote_span(sandbox):
    source_id = publish(sandbox, "medication_event", {
        "concept": "medication", "value": "oxybutynin 5 mg", "event_type": "ordered",
        "order_id": "synthetic-order-1"})
    canonical, tags, facts = tags_of(sandbox, source_id)
    (tag,) = tags
    assert (tag["kind"], tag["tag"], tag["extracted_by"]) == ("amplifier", "high_risk_med_new", "structured")
    assert canonical[tag["start_offset"]:tag["end_offset"]] == tag["quote"]
    assert "oxybutynin" in tag["quote"]
    assert tag["valid_to"] - tag["valid_from"] == timedelta(days=7)
    fact = facts[tag["fact_id"]]
    assert (fact["start_offset"], fact["end_offset"], fact["quote"]) == (
        tag["start_offset"], tag["end_offset"], tag["quote"])


def test_unlisted_drug_and_normal_temperature_create_no_tags(sandbox):
    drug = publish(sandbox, "medication_event", {
        "concept": "medication", "value": "paracetamol 500 mg", "event_type": "ordered",
        "order_id": "synthetic-order-2"})
    normal = publish(sandbox, "observation", {"concept": "temperature_c", "value": 37.1})
    assert tags_of(sandbox, drug)[1] == []
    assert tags_of(sandbox, normal)[1] == []


def test_purging_a_source_removes_its_tags_and_quotes(sandbox):
    cfg, pid, actors, objects = sandbox
    source_id = publish(sandbox, "medication_event", {
        "concept": "medication", "value": "oxybutynin 5 mg", "event_type": "ordered",
        "order_id": "synthetic-order-3"})
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE sources SET purge_requested=true,purge_after=now() WHERE id=%s", (source_id,))
    assert run_once(cfg, actors["importer"], objects)
    _, tags, _ = tags_of(sandbox, source_id)
    assert tags == []


def test_fever_observation_creates_tag(sandbox):
    source_id = publish(sandbox, "observation", {"concept": "temperature_c", "value": 38.2})
    _, (tag,), _ = tags_of(sandbox, source_id)
    assert tag["tag"] == "fever_documented"
