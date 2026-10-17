from datetime import timedelta
from uuid import UUID, uuid4

from patient_memory.domain import SourceInput, now
from patient_memory.ingestion import submit
from patient_memory.retrieval import retrieve
from patient_memory.storage import transaction
from patient_memory.worker import run_once


def publish(sandbox, source):
    cfg, pid, actors, objects = sandbox
    with transaction(cfg, actors["importer"]) as conn:
        job = submit(conn, actors["importer"], pid, source, str(uuid4()), objects)
    run_once(cfg, actors["importer"], objects)
    return UUID(job["source_version_id"])


def test_temporal_correction_and_missing_evidence(sandbox):
    cfg, pid, actors, _ = sandbox
    old = SourceInput(external_document_id="synthetic", external_version_id="1",
                      source_system="synthetic", kind="nursing_note", author_role="nurse",
                      recorded_at=now(), effective_from=now() - timedelta(hours=1),
                      text="Sleep was interrupted.")
    parent = publish(sandbox, old)
    cutoff = now()
    publish(sandbox, old.model_copy(update={"external_version_id": "2",
            "supersedes_version_id": parent, "text": "Sleep was improved."}))
    with transaction(cfg, actors["nurse"]) as conn:
        historical, _ = retrieve(conn, pid, now(), cutoff, "sleep")
        current, _ = retrieve(conn, pid, now(), now(), "sleep")
        missing, _ = retrieve(conn, pid, now(), now(), "allergies")
        assert [f["quote"] for f in historical] == ["Sleep was interrupted."]
        assert [f["quote"] for f in current] == ["Sleep was improved."]
        assert missing == []


def test_patient_visibility_is_filtered_inside_database(sandbox):
    cfg, pid, actors, _ = sandbox
    source = SourceInput(external_document_id="synthetic-private", external_version_id="1",
                         source_system="synthetic", kind="nursing_note", author_role="nurse",
                         recorded_at=now(), text="Private sleep observation.")
    publish(sandbox, source)
    with transaction(cfg, actors["patient"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
        facts, coverage = retrieve(conn, pid, now(), now(), "sleep")
        assert not facts and coverage["index_complete"]


def test_documentation_boilerplate_does_not_establish_relevance(sandbox):
    cfg, pid, actors, _ = sandbox
    source = SourceInput(external_document_id="synthetic-intake", external_version_id="1",
                         source_system="synthetic", kind="nursing_note", author_role="nurse",
                         recorded_at=now(), text="Fluid intake was recorded.")
    publish(sandbox, source)
    with transaction(cfg, actors["nurse"]) as conn:
        facts, _ = retrieve(conn, pid, now(), now(), "Have allergies been recorded?")
        assert facts == []
