from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.notes import extract_pending_notes
from patient_memory.domain import SourceInput, now
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from patient_memory.worker import run_once
from tests.integration.test_baseline_rls import add_source, make_tenant


def publish_note(sandbox, text="Not her usual chatty self.", cfg=None):
    original_cfg, patient, actors, objects = sandbox
    cfg = cfg or original_cfg
    payload = SourceInput(external_document_id=str(uuid4()), external_version_id="1",
                          source_system="synthetic", kind="nursing_note", author_role="nurse",
                          recorded_at=now(), text=text)
    with transaction(cfg, actors["importer"]) as conn:
        result = submit(conn, actors["importer"], patient, payload, str(uuid4()), objects)
    assert run_once(cfg, actors["importer"], objects)
    return result["source_version_id"]


def test_worker_publishes_model_tags_exact_spans_and_discards_fabricated_quote(sandbox, monkeypatch):
    cfg, pid, actors, _ = sandbox
    configured = cfg.model_copy(update={"provider": "compatible",
        "provider_url": "https://synthetic.invalid", "provider_model": "synthetic"})
    monkeypatch.setattr("patient_memory.baseline.llm.request_json", lambda *a, **kw: {"tags": [
        {"tag": "new_confusion_noted", "quote": "Not her usual chatty self"},
        {"tag": "recent_fall", "quote": "Invented fall"}]})
    source_id = publish_note(sandbox, "🙂 Not her usual chatty self.", configured)
    with transaction(cfg, actors["nurse"]) as conn:
        (tag,) = conn.execute("SELECT * FROM context_tags WHERE source_id=%s", (source_id,)).fetchall()
        canonical = conn.execute("SELECT canonical_text FROM sources WHERE id=%s",
                                 (source_id,)).fetchone()["canonical_text"]
        fact = conn.execute("SELECT * FROM facts WHERE id=%s", (tag["fact_id"],)).fetchone()
        assert canonical[tag["start_offset"]:tag["end_offset"]] == tag["quote"]
        assert fact["quote"] == canonical and fact["polarity"] == "uncertain"
        assert tag["extracted_by"] == "gemini"
    with transaction(cfg, actors["importer"]) as conn:
        before = conn.execute("SELECT revision FROM patients WHERE id=%s", (pid,)).fetchone()
        assert extract_pending_notes(conn, actors["importer"], pid, cfg).processed == 0
        assert conn.execute("SELECT revision FROM patients WHERE id=%s", (pid,)).fetchone() == before


def test_empty_note_is_processed_once_without_changing_earlier_evidence(sandbox):
    cfg, pid, actors, _ = sandbox
    source_id = publish_note(sandbox, "Enjoyed lunch today.")
    with transaction(cfg, actors["importer"]) as conn:
        assert conn.execute("SELECT method FROM note_context_runs WHERE source_id=%s",
                            (source_id,)).fetchone()["method"] == "keyword"
        assert extract_pending_notes(conn, actors["importer"], pid, cfg).processed == 0
        assert conn.execute("SELECT count(*) AS n FROM facts WHERE source_id=%s",
                            (source_id,)).fetchone()["n"] == 1


def test_on_demand_extracts_legacy_note_and_skips_retracted_source(sandbox):
    cfg, pid, actors, _ = sandbox
    source_id = publish_note(sandbox)
    # Synthetic legacy state: the source was published before BL-10 existed.
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("DELETE FROM context_tags WHERE source_id=%s", (source_id,))
        admin.execute("DELETE FROM note_context_runs WHERE source_id=%s", (source_id,))
    with transaction(cfg, actors["importer"]) as conn:
        result = extract_pending_notes(conn, actors["importer"], pid, cfg)
        assert (result.processed, result.tags_created, result.methods) == (1, 1, ["keyword"])
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("DELETE FROM note_context_runs WHERE source_id=%s", (source_id,))
        admin.execute("UPDATE sources SET retracted_at=clock_timestamp() WHERE id=%s", (source_id,))
    with transaction(cfg, actors["importer"]) as conn:
        assert extract_pending_notes(conn, actors["importer"], pid, cfg).processed == 0


def test_explicit_retry_upgrades_keyword_marker_without_duplicating_or_removing_tags(sandbox, monkeypatch):
    cfg, pid, actors, _ = sandbox
    source_id = publish_note(sandbox)
    configured = cfg.model_copy(update={"provider": "compatible",
        "provider_url": "https://synthetic.invalid", "provider_model": "synthetic"})
    monkeypatch.setattr("patient_memory.baseline.llm.request_json", lambda *a, **kw: {"tags": [
        {"tag": "new_confusion_noted", "quote": "Not her usual chatty self."}]})
    with transaction(cfg, actors["importer"]) as conn:
        assert extract_pending_notes(conn, actors["importer"], pid, configured,
                                     retry_fallback=True).processed == 1
        assert conn.execute("SELECT method FROM note_context_runs WHERE source_id=%s",
                            (source_id,)).fetchone()["method"] == "gemini"
        assert conn.execute("SELECT count(*) AS n FROM context_tags WHERE source_id=%s",
                            (source_id,)).fetchone()["n"] == 1
        assert extract_pending_notes(conn, actors["importer"], pid, configured,
                                     retry_fallback=True).processed == 0


def test_purge_removes_quotes_and_never_reextracts(sandbox):
    cfg, pid, actors, objects = sandbox
    source_id = publish_note(sandbox)
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE sources SET purge_requested=true,purge_after=now() WHERE id=%s", (source_id,))
    assert run_once(cfg, actors["importer"], objects)
    with transaction(cfg, actors["importer"]) as conn:
        assert extract_pending_notes(conn, actors["importer"], pid, cfg).processed == 0
        assert conn.execute("SELECT count(*) AS n FROM context_tags WHERE source_id=%s",
                            (source_id,)).fetchone()["n"] == 0


def test_note_run_table_forced_rls_other_tenant_invisible_and_cross_patient_fk(sandbox):
    cfg, pid, actors, _ = sandbox
    own_source = publish_note(sandbox)
    with psycopg.connect(cfg.admin_database_url) as admin:
        tenant, other_pid, _ = make_tenant(admin)
        other_source = add_source(admin, tenant, other_pid)
        admin.execute("INSERT INTO note_context_runs(tenant_id,patient_id,source_id,method) "
                      "VALUES(%s,%s,%s,'keyword')", (tenant, other_pid, other_source))
        assert admin.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
                             "WHERE relname='note_context_runs'").fetchone()[0]
    with transaction(cfg, actors["nurse"]) as conn:
        rows = conn.execute("SELECT source_id FROM note_context_runs").fetchall()
        assert [str(row["source_id"]) for row in rows] == [own_source]
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with transaction(cfg, actors["importer"]) as conn:
            conn.execute("INSERT INTO note_context_runs(tenant_id,patient_id,source_id,method) "
                         "VALUES(%s,%s,%s,'keyword')", (actors["importer"].tenant_id, pid, other_source))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(cfg, actors["nurse"]) as conn:
            conn.execute("INSERT INTO note_context_runs(tenant_id,patient_id,source_id,method) "
                         "VALUES(%s,%s,%s,'keyword')", (actors["nurse"].tenant_id, pid, uuid4()))
