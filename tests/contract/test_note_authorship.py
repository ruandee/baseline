"""BL-31 attribution is importer asserted; PSW feedback reveals only positive own-note credit."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest

from patient_memory.baseline.overview import _latest_assessment
from patient_memory.domain import SourceInput
from patient_memory.storage import transaction
from tests.contract.test_api import client_for, import_note, source_payload
from tests.contract.test_resident_checks import SCORE_FIELDS
from tests.integration.test_assessments import SLOW, seed_checks, store


def authored(sandbox, role="psw", **changes):
    body = source_payload("Poor intake. Not her usual chatty self.",
                          author_role=role,
                          author_principal_id=str(sandbox[2][role].principal_id),
                          effective_from=(datetime.now(UTC) - timedelta(hours=1)).isoformat())
    body.update(changes)
    return body


def feedback(sandbox):
    response = client_for(sandbox, "psw").get("/v1/checks/due")
    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["residents"] if r["patient_id"] == str(sandbox[1]))
    assert not SCORE_FIELDS.intersection(row)
    assert set(row) == {"patient_id", "display_name", "status", "consent_state", "last_check_ts",
                        "skipped_today", "observation_helped"}
    return row["observation_helped"]


def escalated(sandbox, note=None):
    imported = import_note(sandbox, note or authored(sandbox))
    seed_checks(sandbox, 6)
    result = store(sandbox, SLOW)
    if result.assessment["verdict"] != "escalate":
        result = store(sandbox, SLOW)
    assert result.assessment["verdict"] == "escalate"
    return imported, result


def test_explicit_psw_note_author_can_get_only_positive_own_citation_feedback(sandbox):
    imported, result = escalated(sandbox)
    assert feedback(sandbox) is True
    cfg, pid, actors, _ = sandbox
    with transaction(cfg, actors["nurse"]) as conn:
        mapping = conn.execute("SELECT * FROM source_authors WHERE source_id=%s",
                               (imported["source_version_id"],)).fetchone()
        assert mapping["author_principal_id"] == actors["psw"].principal_id
        assert mapping["asserted_by"] == actors["importer"].principal_id
        fact = conn.execute("SELECT id FROM facts WHERE source_id=%s LIMIT 1",
                            (imported["source_version_id"],)).fetchone()["id"]
    psw = client_for(sandbox, "psw")
    root = f"/v1/patients/{pid}"
    for suffix in ("/timeline", f"/evidence/{fact}", "/overview",
                   f"/assessments/{result.assessment['id']}/note"):
        assert psw.get(root + suffix).status_code == 404
    assert psw.post(root + "/sources", json=authored(sandbox),
                    headers={"Idempotency-Key": str(uuid4())}).status_code == 404
    with transaction(cfg, actors["psw"]) as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_authors").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM assessments").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM facts").fetchone()["n"] == 0
        assert conn.execute("SELECT pm_latest_resident_assessment_id(%s,now()) AS id",
                            (pid,)).fetchone()["id"] is None


@pytest.mark.parametrize("note_kind", ["legacy", "other_author", "uncited"])
def test_missing_other_or_uncited_authorship_never_infers_credit(sandbox, note_kind):
    if note_kind == "legacy":
        note = source_payload("Poor intake.")
    elif note_kind == "other_author":
        note = authored(sandbox, "nurse")
    else:
        import_note(sandbox, authored(sandbox, external_document_id="synthetic-uncited",
                                     text="Enjoyed lunch today."))
        note = source_payload("Poor intake.")
    escalated(sandbox, note)
    assert feedback(sandbox) is None


@pytest.mark.parametrize("case", ["foreign", "wrong_role", "inactive", "unassigned"])
def test_importer_rejects_invalid_explicit_author_before_object_work(sandbox, monkeypatch, case):
    cfg, pid, actors, objects = sandbox
    body = authored(sandbox)
    if case == "foreign":
        body["author_principal_id"] = str(uuid4())
    elif case == "wrong_role":
        body["author_principal_id"] = str(actors["nurse"].principal_id)
    else:
        with psycopg.connect(cfg.admin_database_url) as admin:
            if case == "inactive":
                admin.execute("UPDATE principals SET active=false WHERE id=%s",
                              (actors["psw"].principal_id,))
            else:
                admin.execute("UPDATE assignments SET active=false WHERE patient_id=%s "
                              "AND principal_id=%s", (pid, actors["psw"].principal_id))
    monkeypatch.setattr(objects, "put", lambda *a: pytest.fail("invalid author stored bytes"))
    response = client_for(sandbox, "importer").post(f"/v1/patients/{pid}/sources", json=body,
                                                   headers={"Idempotency-Key": str(uuid4())})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "invalid_note_author"


def test_legacy_payload_bytes_hash_and_replay_stay_exactly_compatible(sandbox):
    cfg, pid, actors, _ = sandbox
    body = source_payload("Synthetic unchanged note.", external_document_id="legacy-hash",
                          recorded_at="2026-01-02T10:00:00Z")
    legacy = SourceInput.model_validate(body).model_dump(mode="json")
    assert "author_principal_id" not in legacy
    expected = json.dumps(legacy, sort_keys=True).encode()
    imported = import_note(sandbox, body)
    with transaction(cfg, actors["nurse"]) as conn:
        source = conn.execute("SELECT payload,payload_hash FROM sources WHERE id=%s",
                              (imported["source_version_id"],)).fetchone()
        assert source["payload"] == legacy
        assert source["payload_hash"] == hashlib.sha256(expected).hexdigest()
        assert conn.execute("SELECT count(*) AS n FROM source_authors WHERE source_id=%s",
                            (imported["source_version_id"],)).fetchone()["n"] == 0
    again = import_note(sandbox, body)
    assert again["source_version_id"] == imported["source_version_id"]


@pytest.mark.parametrize("mutation", ["retract", "purge", "expired_fact", "expired_context",
                                      "invalidated", "revision", "latest_watch", "stale",
                                      "over_budget", "no_escalate", "session", "superseded"])
def test_feedback_withholds_when_current_escalation_or_exact_evidence_is_ineligible(sandbox, mutation):
    imported, result = escalated(sandbox)
    assert feedback(sandbox) is True
    cfg, pid, _, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as admin:
        source = imported["source_version_id"]
        aid = result.assessment["id"]
        if mutation in ("retract", "purge"):
            column = "retracted_at" if mutation == "retract" else "purged_at"
            admin.execute(f"UPDATE sources SET {column}=clock_timestamp() WHERE id=%s", (source,))
        elif mutation == "superseded":
            admin.execute("INSERT INTO sources(id,tenant_id,patient_id,document_key,external_version,"
                          "payload_hash,object_key,payload,visibility,recorded_at,canonical_text,"
                          "published_at,supersedes) SELECT %s,tenant_id,patient_id,document_key,"
                          "'synthetic-amendment',payload_hash,object_key,payload,visibility,"
                          "recorded_at,canonical_text,clock_timestamp(),id FROM sources WHERE id=%s",
                          (uuid4(), source))
        elif mutation == "expired_fact":
            admin.execute("UPDATE facts SET valid_to=clock_timestamp()-interval '1 second' "
                          "WHERE source_id=%s", (source,))
        elif mutation == "expired_context":
            admin.execute("UPDATE context_tags SET valid_to=clock_timestamp()-interval '1 second' "
                          "WHERE source_id=%s", (source,))
        elif mutation == "revision":
            admin.execute("UPDATE patients SET revision=revision+1 WHERE id=%s", (pid,))
        elif mutation == "latest_watch":
            admin.execute("UPDATE assessments SET verdict='watch' WHERE id=%s", (aid,))
        elif mutation == "stale":
            admin.execute("UPDATE assessments SET params=jsonb_set(params,'{signal_ts}',"
                          "to_jsonb(clock_timestamp()-interval '25 hours')) WHERE id=%s", (aid,))
        elif mutation == "session":
            admin.execute("UPDATE assessments SET params=params||%s::jsonb WHERE id=%s",
                          (json.dumps({"session_id": str(uuid4())}), aid))
        else:
            admin.execute("UPDATE assessments SET params=params||%s::jsonb WHERE id=%s",
                          (json.dumps({mutation: True}), aid))
    assert feedback(sandbox) is None


def test_revoked_psw_and_care_membership_hides_feedback_and_latest_helper(sandbox):
    _, result = escalated(sandbox)
    cfg, pid, actors, _ = sandbox
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("UPDATE assignments SET active=false WHERE patient_id=%s "
                      "AND principal_id IN (%s,%s)",
                      (pid, actors["psw"].principal_id, actors["nurse"].principal_id))
    with transaction(cfg, actors["psw"]) as conn:
        assert conn.execute("SELECT pm_observation_helped(%s) AS helped", (pid,)).fetchone()["helped"] is None
    with transaction(cfg, actors["nurse"]) as conn:
        assert _latest_assessment(conn, pid) is None
        assert conn.execute("SELECT pm_latest_resident_assessment_id(%s,now()) AS id",
                            (pid,)).fetchone()["id"] is None
    assert client_for(sandbox).get(f"/v1/patients/{pid}/overview").status_code == 404


def test_source_author_mapping_is_immutable_and_cannot_be_attached_to_another_payload(sandbox):
    imported = import_note(sandbox, authored(sandbox))
    legacy = import_note(sandbox, source_payload("Synthetic unrelated note."))
    cfg, pid, actors, _ = sandbox
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(cfg, actors["importer"]) as conn:
            conn.execute("UPDATE source_authors SET author_role='nurse' WHERE source_id=%s",
                         (imported["source_version_id"],))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with transaction(cfg, actors["importer"]) as conn:
            conn.execute("INSERT INTO source_authors(tenant_id,patient_id,source_id,"
                         "author_principal_id,author_role,asserted_by) VALUES(%s,%s,%s,%s,'psw',%s)",
                         (actors["importer"].tenant_id, pid, legacy["source_version_id"],
                          actors["psw"].principal_id, actors["importer"].principal_id))


@pytest.mark.parametrize("case", ["current", "invalidated", "old_revision", "future", "session",
                                  "motion"])
def test_shared_latest_helper_preserves_the_original_overview_eligibility(sandbox, case):
    _, result = escalated(sandbox)
    cfg, pid, actors, _ = sandbox
    aid = result.assessment["id"]
    patches = {
        "invalidated": {"invalidated": True}, "old_revision": {"source_revision": -1},
        "future": {"signal_ts": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
        "session": {"session_id": str(uuid4())},
        "motion": {"modality": "motion", "signal_ts": datetime.now(UTC).isoformat()},
    }
    if case in patches:
        with psycopg.connect(cfg.admin_database_url) as admin:
            admin.execute("UPDATE assessments SET params=params||%s::jsonb WHERE id=%s",
                          (json.dumps(patches[case]), aid))
    at = datetime.now(UTC)
    with transaction(cfg, actors["nurse"]) as conn:
        for modality in (None, "speech", "motion"):
            # Exact pre-013 eligibility/order, kept only as a regression oracle.
            old = conn.execute(
                "SELECT * FROM (SELECT a.id,a.created_at,"
                "COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) AS check_ts "
                "FROM assessments a LEFT JOIN voice_checks v ON v.tenant_id=a.tenant_id "
                "AND v.patient_id=a.patient_id AND v.id=a.check_id WHERE a.patient_id=%s "
                "AND COALESCE((a.params->>'invalidated')::boolean,false)=false "
                "AND a.params->>'session_id' IS NULL AND v.session_id IS NULL "
                "AND (%s::text IS NULL OR COALESCE(a.params->>'modality','speech')=%s) "
                "AND (a.params->>'source_revision')::bigint="
                "(SELECT revision FROM patients WHERE id=%s)) eligible WHERE check_ts<=%s "
                "ORDER BY check_ts DESC,created_at DESC,id DESC LIMIT 1",
                (pid, modality, modality, pid, at)).fetchone()
            new = _latest_assessment(conn, pid, modality, at)
            assert (new and new["id"]) == (old and old["id"])
