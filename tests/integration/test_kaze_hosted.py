"""Hosted KAZE setup and worker against real forced-RLS storage, with no external sender."""
from uuid import UUID, uuid4

import psycopg

from patient_memory import worker
from patient_memory.auth import decode_token
from patient_memory.consent import consent_state
from patient_memory.storage import transaction
from scripts import hosted_demo, kaze_demo
from tests.integration.test_safety_rls import add_session


def test_bootstrap_is_separate_contact_free_and_never_overrides_withdrawal(
        sandbox, monkeypatch, tmp_path):
    cfg = sandbox[0]
    ids = {}
    monkeypatch.setattr(kaze_demo, "uid", lambda name: ids.setdefault(name, uuid4()))
    payload = hosted_demo.bootstrap_kaze(cfg, destination=tmp_path / "session.json")
    person = payload["people"][0]
    identity = decode_token(person["token"], cfg)
    pid = UUID(person["patient_id"])
    assert identity.tenant_id != sandbox[2]["nurse"].tenant_id
    with transaction(cfg, identity) as conn:
        assert consent_state(conn, pid) == "unknown"
        assert conn.execute("SELECT count(*) AS n FROM safety_sessions").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM safety_contacts").fetchone()["n"] == 0
        assert conn.execute("SELECT id FROM patients WHERE id=%s", (sandbox[1],)).fetchone() is None
    hosted_demo.bootstrap_kaze(cfg, grant_consent=True, destination=tmp_path / "session.json")
    with transaction(cfg, identity) as conn:
        assert consent_state(conn, pid) == "granted"
    with psycopg.connect(cfg.admin_database_url) as admin:
        admin.execute("INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,"
                      "decided_by,recorded_by) VALUES(%s,%s,%s,'voice_check','withdrawn',"
                      "'synthetic_fixture',%s)", (identity.tenant_id, pid, uuid4(), pid))
    hosted_demo.bootstrap_kaze(cfg, grant_consent=True, destination=tmp_path / "session.json")
    with transaction(cfg, identity) as conn:
        assert consent_state(conn, pid) == "withdrawn"


def test_deployed_kaze_entrypoint_advances_and_deletes_only_its_own_tenant(
        kaze_sandbox, sandbox, monkeypatch):
    k = kaze_sandbox
    with psycopg.connect(k["cfg"].admin_database_url, autocommit=True) as admin:
        active = add_session(admin, k["tenant"], k["patient"], status="active", episode=0)
        admin.execute("UPDATE safety_sessions SET next_due_at=clock_timestamp()-interval '3 minutes'"
                      " WHERE id=%s", (active,))
        expired = add_session(admin, k["tenant"], k["other_patient"], status="ended",
                              created=-100000, ends=-90000, ended=-90000)
        runtime = k["cfg"].model_copy(update={"admin_database_url": ""})
        service = k["ids"]["service"]
        monkeypatch.setattr(hosted_demo, "deployment_settings", lambda: runtime)
        monkeypatch.setattr(hosted_demo, "uid", lambda name: {
            "kaze-demo/service": service.principal_id, "kaze-demo": service.tenant_id}[name])
        loop = worker.run_worker
        monkeypatch.setattr(worker, "run_worker", lambda cfg, identity: loop(cfg, identity, once=True))
        monkeypatch.setattr("sys.argv", ["hosted_demo", "kaze-worker"])
        hosted_demo.main()
        assert admin.execute("SELECT id FROM safety_sessions WHERE id=%s", (expired,)).fetchone() is None
        assert admin.execute("SELECT level,channel,delivery FROM escalation_events WHERE session_id=%s",
                             (active,)).fetchall() == [(1, "nudge", "logged")]
        assert admin.execute("SELECT count(*) FROM patients WHERE id=%s", (sandbox[1],)).fetchone() == (1,)
