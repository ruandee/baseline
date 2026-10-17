"""Real RLS/publication/scoring checks; no provider or audio calls."""
import psycopg
import pytest

from patient_memory.auth import Identity
from patient_memory.errors import Problem
from patient_memory.ingestion import submit
from patient_memory.storage import transaction
from patient_memory.worker import run_once
from scripts.load_baseline_demo import DemoScope, LoaderError, load_demo
from tests.contract.test_api import client_for, source_payload


def scope_for(sandbox):
    actors = sandbox[2]
    return DemoScope(actors["importer"].tenant_id, actors["importer"].principal_id,
                     actors["nurse"].principal_id)


def counts(sandbox, scope):
    with transaction(sandbox[0], scope.nurse) as conn:
        return [conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in ("voice_checks", "sources", "assessments")]


def test_loads_real_scoped_sources_and_assessments_idempotently(sandbox):
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    first, session = load_demo(cfg, objects=objects, scope=scope, offline=True,
                               presentation="scenario-snapshots")
    assert first["checks_loaded"] == 353 and len(session["patients"]) == 12
    assert all(c["exact_span_verified"] for c in first["context"])
    assert first["sources_published_before_assessments"]
    before = counts(sandbox, scope)
    second, again = load_demo(cfg, objects=objects, scope=scope, offline=True,
                              presentation="scenario-snapshots")
    assert counts(sandbox, scope) == before == [353, 4, 353]
    assert first == second and session["patients"] == again["patients"]
    # Accepted engine with the original +20% fixture honestly reports the remaining T gate.
    # PR #61 adopts the separately approved +35% scenario and strengthens this to all matches.
    assert first["matches_spec"] is False
    assert {r["resident"] for r in first["outcomes"] if not r["matches_spec"]} == {"synthetic-mr-t"}
    mrs_l = next(r for r in first["outcomes"] if r["resident"] == "synthetic-mrs-l")
    assert mrs_l["actual_snapshot"]["verdict"] == "watch"
    assert mrs_l["actual_snapshot"]["suggested_action"] == "recheck_1h"
    with transaction(cfg, scope.nurse) as conn:
        assert conn.execute(
            "SELECT count(*) AS n FROM assessments a JOIN patients p ON p.tenant_id=a.tenant_id "
            "AND p.id=a.patient_id WHERE (a.params->>'source_revision')::bigint<>p.revision"
        ).fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM voice_checks WHERE NOT synthetic "
                            "OR transcript IS NOT NULL OR words IS NOT NULL").fetchone()["n"] == 0
    # A real evidence endpoint resolves every displayed Mrs. K context fact.
    nurse = client_for(sandbox, "nurse")
    pid = session["patients"][0]["id"]
    page = nurse.get(f"/v1/patients/{pid}/overview").json()
    assert page["latest_assessment"]["verdict"] == "escalate"
    for reason in page["latest_assessment"]["reasons"]:
        assert nurse.get(f"/v1/patients/{pid}/evidence/{reason['evidence_id']}").status_code == 200


def test_full_history_is_explicit_and_cannot_be_destructively_truncated(sandbox):
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    report, _ = load_demo(cfg, objects=objects, scope=scope, offline=True,
                          presentation="all-history")
    assert report["checks_loaded"] == 360
    assert all(outcome["latest"]["day"] == 30 for outcome in report["outcomes"])
    before = counts(sandbox, scope)
    with pytest.raises(LoaderError, match="exceed this mode"):
        load_demo(cfg, objects=objects, scope=scope, offline=True,
                  presentation="scenario-snapshots")
    assert counts(sandbox, scope) == before


def test_other_tenant_and_revoked_assignment_cannot_load_or_read(sandbox):
    cfg, _, actors, objects = sandbox
    scope = scope_for(sandbox)
    load_demo(cfg, objects=objects, scope=scope, offline=True, presentation="scenario-snapshots")
    other = DemoScope()
    with transaction(cfg, Identity(scope.nurse_id, other.tenant_id)) as conn:
        assert conn.execute("SELECT count(*) AS n FROM voice_checks").fetchone()["n"] == 0
    with psycopg.connect(cfg.admin_database_url) as conn:
        conn.execute("UPDATE assignments SET active=false WHERE tenant_id=%s AND patient_id=%s "
                     "AND principal_id=%s", (scope.tenant_id, scope.patient_id(0),
                                              actors["importer"].principal_id))
    with pytest.raises(Problem) as denied:
        load_demo(cfg, objects=objects, scope=scope, offline=True,
                  presentation="scenario-snapshots")
    assert denied.value.status == 404


def test_unlisted_source_with_the_same_system_stamp_is_rejected_before_rescoring(sandbox):
    from patient_memory.domain import SourceInput
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    load_demo(cfg, objects=objects, scope=scope, offline=True, presentation="scenario-snapshots")
    extra = SourceInput.model_validate(source_payload(
        "New confusion noted.", source_system="synthetic-baseline"))
    with transaction(cfg, scope.importer) as conn:
        submit(conn, scope.importer, scope.patient_id(0), extra, "unlisted-synthetic-source", objects)
    assert run_once(cfg, scope.importer, objects)
    before = counts(sandbox, scope)
    with pytest.raises(LoaderError, match="unlisted or conflicting"):
        load_demo(cfg, objects=objects, scope=scope, offline=True,
                  presentation="scenario-snapshots")
    assert counts(sandbox, scope) == before


@pytest.mark.parametrize("corruption", ["tag_quote", "linked_fact"])
def test_invalid_context_support_is_not_reported_as_verified(sandbox, corruption):
    cfg, _, _, objects = sandbox
    scope = scope_for(sandbox)
    load_demo(cfg, objects=objects, scope=scope, offline=True, presentation="scenario-snapshots")
    with psycopg.connect(cfg.admin_database_url) as conn:
        if corruption == "tag_quote":
            conn.execute("UPDATE context_tags SET quote='Quiet at lunch',start_offset=0,end_offset=14 "
                         "WHERE tenant_id=%s AND patient_id=%s AND tag='poor_intake'",
                         (scope.tenant_id, scope.patient_id(0)))
        else:
            conn.execute(
                "UPDATE context_tags t SET fact_id=(SELECT f.id FROM facts f WHERE "
                "f.tenant_id=t.tenant_id AND f.patient_id=t.patient_id AND f.source_id=t.source_id "
                "AND f.quote LIKE 'Not her usual%%' LIMIT 1) "
                "WHERE t.tenant_id=%s AND t.patient_id=%s AND t.tag='poor_intake'",
                (scope.tenant_id, scope.patient_id(0)))
    with pytest.raises(LoaderError, match="context is incomplete"):
        load_demo(cfg, objects=objects, scope=scope, offline=True,
                  presentation="scenario-snapshots")
