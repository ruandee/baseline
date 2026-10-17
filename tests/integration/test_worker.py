from uuid import uuid4

from patient_memory.domain import SourceInput, now
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from patient_memory.worker import run_once


def test_real_object_integrity_and_atomic_publish(sandbox):
    cfg, pid, actors, objects = sandbox
    source = SourceInput(external_document_id="synthetic-sleep", external_version_id="1",
                         source_system="synthetic", kind="nursing_note", author_role="nurse",
                         text="Patient reports improved sleep. 😀", recorded_at=now())
    with transaction(cfg, actors["importer"]) as conn:
        result = submit(conn, actors["importer"], pid, source, str(uuid4()), objects)
    assert run_once(cfg, actors["importer"], objects)
    with transaction(cfg, actors["nurse"]) as conn:
        assert conn.execute("SELECT status FROM jobs WHERE id=%s", (result["job_id"],)).fetchone()["status"] == "completed"
        row = conn.execute("SELECT * FROM sources WHERE id=%s", (result["source_version_id"],)).fetchone()
        facts = conn.execute("SELECT * FROM facts WHERE source_id=%s", (row["id"],)).fetchall()
        assert facts
        assert all(row["canonical_text"][f["start_offset"]:f["end_offset"]] == f["quote"] for f in facts)
        assert conn.execute("SELECT revision FROM patients WHERE id=%s", (pid,)).fetchone()["revision"] == 1
    assert not run_once(cfg, actors["importer"], objects)
