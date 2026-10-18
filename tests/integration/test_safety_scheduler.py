"""BL-26's runtime-role scheduler: real row locks, clock boundaries and isolation."""
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from patient_memory.baseline.safety import STANDARD, LogSender, advance, run_pass
from patient_memory.baseline.sessions import after_check
from patient_memory.storage import transaction
from tests.integration.test_safety_rls import add_event, add_session, clock


@pytest.fixture
def admin(kaze_sandbox):
    with psycopg.connect(kaze_sandbox["cfg"].admin_database_url, autocommit=True) as conn:
        yield conn


def active(k, admin, **fields):
    sid = add_session(admin, k["tenant"], k["patient"], status="active", episode=0)
    due = clock(admin) - timedelta(minutes=5)
    admin.execute("UPDATE safety_sessions SET next_due_at=%s WHERE id=%s", (due, sid))
    for key, value in fields.items():
        assert key in {"context_tags", "escalation_enabled", "ends_at"}
        admin.execute(f"UPDATE safety_sessions SET {key}=%s WHERE id=%s", (value, sid))
    return sid, due


def events(admin, sid):
    return admin.execute("SELECT episode,level,contact_index,delivery FROM escalation_events "
                         "WHERE session_id=%s ORDER BY sent_at,contact_index", (sid,)).fetchall()


def test_concurrent_worker_passes_record_one_step_only(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, due = active(k, admin)
    barrier = Barrier(2)
    def run():
        barrier.wait(timeout=5)
        return run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=5))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run) for _ in range(2)]
        results = [job.result(timeout=10) for job in jobs]
    assert sorted(len(result) for result in results) == [0, 1]
    assert events(admin, sid) == [(1, 2, 1, "logged")]
    assert run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=15))[0][1].level == 3
    assert events(admin, sid) == [(1, 2, 1, "logged"), (1, 3, 1, "logged")]


def test_races_with_normal_checkin_and_ack_stop_publication(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, due = active(k, admin)
    assert run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=5))
    # An acknowledgement for the current episode freezes progression.
    add_event(admin, k["tenant"], k["patient"], sid, level=3, token="synthetic-ack")
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        assert conn.execute("SELECT pm_acknowledge_escalation(%s) AS state",
                            (hashlib.sha256(b"synthetic-ack").digest(),)).fetchone()["state"] == "acknowledged"
    assert run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=35)) == []
    # A normal usable check-in restarts the timer; an unusable one leaves it untouched.
    with transaction(k["cfg"], k["ids"]["person"]) as conn:
        row = conn.execute("SELECT * FROM safety_sessions WHERE id=%s FOR UPDATE", (sid,)).fetchone()
        ts = clock(admin)
        after_check(conn, row, ts, False, False, None)
        assert conn.execute("SELECT status FROM safety_sessions WHERE id=%s", (sid,)).fetchone()["status"] == "acknowledged"
        after_check(conn, row, ts, True, False, "none")
    assert run_pass(k["cfg"], k["ids"]["service"], now=ts) == []
    next_episode = run_pass(k["cfg"], k["ids"]["service"], now=ts + timedelta(minutes=50))
    assert next_episode[0][1].episode == 2


@pytest.mark.parametrize("tags,expected", [([], 2), (["exertion"], None), (["loud_venue"], None)])
def test_raw_change_uses_only_session_explainers(kaze_sandbox, admin, tags, expected):
    k = kaze_sandbox
    sid, due = active(k, admin, context_tags=tags)
    cid = uuid4()
    admin.execute("INSERT INTO voice_checks(tenant_id,patient_id,id,device_id,mode,usable,quality,"
                  "session_id) VALUES(%s,%s,%s,'phone','live',true,%s,%s)",
                  (k["tenant"], k["patient"], cid, Jsonb({}), sid))
    # An unrelated PCC explainer verdict must not silence the raw KAZE change.
    admin.execute("INSERT INTO assessments(tenant_id,patient_id,id,check_id,change_status,features,"
                  "params,verdict,suggested_action) VALUES(%s,%s,%s,%s,'change',%s,%s,'explained','none')",
                  (k["tenant"], k["patient"], uuid4(), cid, Jsonb({}), Jsonb({})))
    steps = run_pass(k["cfg"], k["ids"]["service"], now=due)
    assert ([step.level for _, step in steps] or [None]) == [expected]


def test_escalation_disabled_and_assignment_scope(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, due = active(k, admin, escalation_enabled=False)
    # Neither another person nor an unassigned tenant administrator can run this ladder.
    for role in ["other", "admin"]:
        assert run_pass(k["cfg"], k["ids"][role], now=due + timedelta(minutes=30)) == []
    steps = run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=5))
    assert steps[0][1].level == 1
    assert run_pass(k["cfg"], k["ids"]["service"], now=due + timedelta(minutes=30)) == []
    assert events(admin, sid) == [(1, 1, None, "logged")]


def test_expiry_rechecked_after_waiting_for_session_lock(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, _ = active(k, admin)
    expires = clock(admin) + timedelta(seconds=1)
    admin.execute("UPDATE safety_sessions SET ends_at=%s WHERE id=%s", (expires, sid))
    def run():
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            return advance(conn, k["patient"], sid, None, STANDARD, LogSender())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(k["cfg"].admin_database_url) as locker:
            locker.execute("SELECT id FROM safety_sessions WHERE id=%s FOR UPDATE", (sid,))
            future = pool.submit(run)
            try:
                blocked = False
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    blocked = admin.execute("SELECT EXISTS(SELECT FROM pg_stat_activity WHERE "
                                            "%s=ANY(pg_blocking_pids(pid)))",
                                            (locker.info.backend_pid,)).fetchone()[0]
                    if blocked:
                        break
                    time.sleep(.01)
                assert blocked
                admin.execute("SELECT pg_sleep(greatest(0,extract(epoch FROM "
                              "(%s::timestamptz-clock_timestamp())))+.02)", (expires,))
            finally:
                locker.commit()
        assert future.result(timeout=5) is None
    assert events(admin, sid) == []
    ended = admin.execute("SELECT status,ended_at,delete_after FROM safety_sessions WHERE id=%s",
                           (sid,)).fetchone()
    assert ended == ("ended", expires, expires + timedelta(hours=24))


def test_checkin_committed_while_scheduler_waits_cancels_overdue_step(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, _ = active(k, admin)
    def run():
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            return advance(conn, k["patient"], sid, None, STANDARD, LogSender())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction(k["cfg"], k["ids"]["person"]) as owner:
            row = owner.execute("SELECT * FROM safety_sessions WHERE id=%s FOR UPDATE", (sid,)).fetchone()
            future = pool.submit(run)
            blocked = False
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                blocked = admin.execute("SELECT EXISTS(SELECT FROM pg_stat_activity WHERE "
                                        "%s=ANY(pg_blocking_pids(pid)))",
                                        (owner.info.backend_pid,)).fetchone()[0]
                if blocked:
                    break
                time.sleep(.01)
            assert blocked
            ts = clock(admin)
            after_check(owner, row, ts, True, False, "none")
        assert future.result(timeout=5) is None
    assert events(admin, sid) == []
