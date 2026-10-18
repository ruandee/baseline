from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline import context
from patient_memory.storage import transaction
from patient_memory.worker import run_once
from tests.contract.test_api import client_for

BODY = {"kind": "explainer", "tag": "exertion", "label": "Running the Toronto marathon",
        "valid_from": "2026-10-18T12:00:00Z", "valid_to": "2026-10-18T18:00:00Z"}


def post(sandbox, body=BODY, role="importer", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client_for(sandbox, role).post(f"/v1/patients/{sandbox[1]}/context", json=body, headers=headers)


def test_context_record_creates_structured_tag_pointing_at_its_source_span(sandbox):
    response = post(sandbox)
    assert response.status_code == 201, response.text
    tag = response.json()
    assert (tag["kind"], tag["tag"], tag["label"], tag["extracted_by"]) == (
        "explainer", "exertion", "Running the Toronto marathon", "structured")
    assert (tag["valid_from"], tag["valid_to"]) == ("2026-10-18T12:00:00Z", "2026-10-18T18:00:00Z")
    cfg, pid, actors, objects = sandbox
    with transaction(cfg, actors["nurse"]) as conn:
        source = conn.execute("SELECT * FROM sources WHERE id=%s", (tag["source_id"],)).fetchone()
        rows = conn.execute("SELECT * FROM context_tags WHERE patient_id=%s", (pid,)).fetchall()
    (row,) = rows
    assert source["canonical_text"][row["start_offset"]:row["end_offset"]] == row["quote"] == tag["quote"]
    assert "Toronto marathon" in tag["quote"]
    assert (tag["start_offset"], tag["end_offset"]) == (row["start_offset"], row["end_offset"])
    assert source["published_at"] is not None
    evidence = client_for(sandbox, "nurse").get(f"/v1/patients/{pid}/evidence/{row['fact_id']}")
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["quote"] == tag["quote"]
    # The synchronous endpoint completes the job, so no worker pass is necessary.
    assert not run_once(cfg, actors["importer"], objects)


def test_omitted_valid_to_takes_the_taxonomy_window(sandbox):
    body = {"kind": "explainer", "tag": "dentures", "label": "New dentures fitted",
            "valid_from": "2026-10-18T12:00:00Z"}
    assert post(sandbox, body).json()["valid_to"] == "2026-10-25T12:00:00Z"


def test_same_idempotency_key_replays_without_a_second_tag(sandbox):
    key = str(uuid4())
    first, second = post(sandbox, key=key), post(sandbox, key=key)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] == second.json()["id"]
    assert post(sandbox, {**BODY, "label": "Different"}, key=key).status_code == 409
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM context_tags").fetchone()["n"] == 1
        assert conn.execute("SELECT revision FROM patients WHERE id=%s",
                            (sandbox[1],)).fetchone()["revision"] == 1


def test_replaying_after_purge_does_not_bring_the_quote_back(sandbox):
    cfg, pid, actors, objects = sandbox
    key = str(uuid4())
    source_id = post(sandbox, key=key).json()["source_id"]
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE sources SET purge_requested=true,purge_after=now() WHERE id=%s", (source_id,))
    assert run_once(cfg, actors["importer"], objects)
    assert post(sandbox, key=key).status_code == 409
    with transaction(cfg, actors["nurse"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM context_tags").fetchone()["n"] == 0


def test_invalid_context_is_rejected(sandbox):
    assert post(sandbox, {**BODY, "tag": "astrology"}).status_code == 422
    assert post(sandbox, {**BODY, "tag": "language_change"}).status_code == 422
    assert post(sandbox, {**BODY, "kind": "amplifier"}).status_code == 422
    assert post(sandbox, {**BODY, "valid_to": "2026-10-18T11:00:00Z"}).status_code == 422
    assert post(sandbox, {**BODY, "extra": 1}).status_code == 422
    assert post(sandbox, {**BODY, "valid_from": "2026-10-18T12:00:00"}).status_code == 422


def test_only_writers_assigned_to_the_patient_can_add_context(sandbox):
    assert post(sandbox, role="nurse").status_code == 404
    assert post(sandbox, role="patient").status_code == 404
    response = client_for(sandbox, "importer").post(f"/v1/patients/{uuid4()}/context", json=BODY)
    assert response.status_code == 404


def test_publication_failure_rolls_back_source_fact_tag_and_revision(sandbox, monkeypatch):
    def fail_tags(*args):
        raise RuntimeError("synthetic tag storage failure")

    monkeypatch.setattr("patient_memory.baseline.context.store_tags", fail_tags)
    with pytest.raises(RuntimeError, match="synthetic tag storage failure"):
        post(sandbox)
    with transaction(sandbox[0], sandbox[2]["nurse"]) as conn:
        for table in ("sources", "facts", "context_tags", "jobs"):
            assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
        assert conn.execute("SELECT revision FROM patients WHERE id=%s",
                            (sandbox[1],)).fetchone()["revision"] == 0


def test_synchronous_publication_invalidates_an_existing_worker_lease(sandbox, monkeypatch):
    original_submit = context.submit
    stale_token = uuid4()

    def submit_with_existing_lease(conn, *args):
        result = original_submit(conn, *args)
        conn.execute(
            "UPDATE jobs SET status='processing',lease_token=%s,lease_until=now()+interval '1 minute' "
            "WHERE id=%s", (stale_token, result["job_id"]))
        return result

    monkeypatch.setattr(context, "submit", submit_with_existing_lease)
    response = post(sandbox)
    assert response.status_code == 201, response.text
    with transaction(sandbox[0], sandbox[2]["importer"]) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE source_id=%s",
                           (response.json()["source_id"],)).fetchone()
        assert job["status"] == "completed"
        assert job["lease_token"] is None
        # A stale failure handler carrying the previous token cannot revive this completed job.
        assert conn.execute("UPDATE jobs SET status='queued' WHERE id=%s AND lease_token=%s",
                            (job["id"], stale_token)).rowcount == 0
