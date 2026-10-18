"""BL-27 real runtime-role delivery claims, public token scope and retention. No real SMS."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import psycopg
import pytest
from fastapi.testclient import TestClient

from patient_memory.api import create_app
from patient_memory.baseline import ack, sms
from patient_memory.baseline.safety import run_pass
from patient_memory.storage import transaction
from tests.integration.test_safety_rls import add_session, clock


@pytest.fixture
def admin(kaze_sandbox):
    with psycopg.connect(kaze_sandbox["cfg"].admin_database_url, autocommit=True) as conn:
        yield conn


def prepared(k, admin):
    sid = add_session(admin, k["tenant"], k["patient"])
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        row = conn.execute("SELECT * FROM safety_sessions WHERE id=%s FOR UPDATE", (sid,)).fetchone()
        message = sms.prepare_sms(conn, k["cfg"], row, 1, 2, "missed_checkin", clock(admin))
        # Repeating preparation for the same episode/level/contact is a no-op.
        assert sms.prepare_sms(conn, k["cfg"], row, 1, 2, "missed_checkin", clock(admin)) is None
    assert message is not None
    return sid, message


def token_of(message):
    return message.body.split("/ack/")[1].split()[0]


def test_worker_delivers_after_commit_outside_all_locks(kaze_sandbox, admin):
    k = kaze_sandbox
    sid = add_session(admin, k["tenant"], k["patient"], status="active", episode=0)
    now = clock(admin)
    admin.execute("UPDATE safety_sessions SET next_due_at=%s WHERE id=%s",
                  (now - timedelta(minutes=5), sid))
    class Probe:
        name = "test"
        calls = []
        def send(self, message):
            # Real independent connection: the event is committed, and both locks are free.
            with transaction(k["cfg"], k["ids"]["service"]) as conn:
                assert conn.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0)) AS ok",
                                    (str(k["patient"]),)).fetchone()["ok"]
                conn.execute("SELECT id FROM safety_sessions WHERE id=%s FOR UPDATE NOWAIT", (sid,))
                event = conn.execute("SELECT * FROM escalation_events WHERE id=%s", (message.event_id,)).fetchone()
                assert event["delivery_started_at"] is not None and event["delivery"] == "pending"
                assert event["ack_token_hash"] == ack.token_hash(token_of(message))
                assert token_of(message) not in str(event)
            self.calls.append(message)
            return "logged"
    sender = Probe()
    assert run_pass(k["cfg"], k["ids"]["service"], sender, now=now)[0][1].level == 2
    assert len(sender.calls) == 1
    assert run_pass(k["cfg"], k["ids"]["service"], sender, now=now) == []
    assert len(sender.calls) == 1


def test_concurrent_delivery_and_failed_retries_are_at_most_once(kaze_sandbox, admin):
    k = kaze_sandbox
    _, message = prepared(k, admin)
    barrier = Barrier(2)
    class Broken:
        name = "test-failure"
        calls = []
        def send(self, message):
            self.calls.append(message.event_id)
            return "failed"
    sender = Broken()
    def run():
        barrier.wait(timeout=5)
        return sms.send(k["cfg"], k["ids"]["service"], message, sender)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(run) for _ in range(2)]
        assert [job.result(timeout=10) for job in jobs] == ["failed", "failed"]
    assert sender.calls == [message.event_id]
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "failed"
    assert len(sender.calls) == 1
    assert admin.execute("SELECT delivery FROM escalation_events WHERE id=%s",
                          (message.event_id,)).fetchone()[0] == "failed"


def test_revoke_or_ack_before_delivery_claim_prevents_delivery(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, message = prepared(k, admin)
    sender = sms.LogSender(keep=1)
    assert sms.send(k["cfg"], k["ids"]["other"], message, sender) == "failed"
    assert len(sender.outbox) == 0
    assert ack.acknowledge(k["cfg"], token_of(message)) == "acknowledged"
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "failed"
    assert len(sender.outbox) == 0
    assert admin.execute("SELECT status FROM safety_sessions WHERE id=%s", (sid,)).fetchone()[0] == "acknowledged"


def test_claim_survives_crash_and_does_not_resend(kaze_sandbox, admin):
    k = kaze_sandbox
    _, message = prepared(k, admin)
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        assert sms.claim_delivery(conn, message)
    sender = sms.LogSender(keep=1)
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "pending"
    assert len(sender.outbox) == 0
    assert admin.execute("SELECT delivery,delivery_started_at IS NOT NULL FROM escalation_events "
                         "WHERE id=%s", (message.event_id,)).fetchone() == ("pending", True)


def test_concurrent_public_get_ack_is_scoped_and_never_discloses_phi(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, message = prepared(k, admin)
    other = add_session(admin, k["tenant"], k["other_patient"])
    token = token_of(message)
    def get():
        return TestClient(create_app(k["cfg"], objects=k["objects"])).get(f"/ack/{token}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: get(), range(2)))
    for response in responses:
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        for private in [str(sid), str(k["patient"]), "Sam", "+14165550101", token]:
            assert private not in response.text
    assert sum("Your response was recorded" in r.text for r in responses) == 1
    assert admin.execute("SELECT status FROM safety_sessions WHERE id=%s", (other,)).fetchone()[0] == "escalating"
    # Token does not grant table reads on the unauthenticated runtime connection.
    with psycopg.connect(k["cfg"].database_url) as conn:
        assert conn.execute("SELECT count(*) FROM escalation_events").fetchone()[0] == 0


def test_ack_expiry_rechecked_after_competing_session_lock(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, message = prepared(k, admin)
    expires = clock(admin) + timedelta(seconds=1)
    admin.execute("UPDATE safety_sessions SET ends_at=%s WHERE id=%s", (expires, sid))
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(k["cfg"].admin_database_url) as locker:
            locker.execute("SELECT id FROM safety_sessions WHERE id=%s FOR UPDATE", (sid,))
            future = pool.submit(ack.acknowledge, k["cfg"], token_of(message))
            blocked = False
            try:
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
        assert future.result(timeout=7) == "invalid"
    assert admin.execute("SELECT status,ended_at,delete_after FROM safety_sessions WHERE id=%s",
                          (sid,)).fetchone() == ("ended", expires, expires + timedelta(hours=24))
    assert admin.execute("SELECT ack_at FROM escalation_events WHERE id=%s",
                          (message.event_id,)).fetchone()[0] is None


def test_retention_removes_claim_and_hash_and_revokes_public_token(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, message = prepared(k, admin)
    token = token_of(message)
    ended = clock(admin) - timedelta(hours=25)
    admin.execute("UPDATE safety_sessions SET status='ended',ended_at=%s,"
                  "end_reason='user',delete_after=%s,next_due_at=NULL WHERE id=%s",
                  (ended, ended + timedelta(hours=24), sid))
    with transaction(k["cfg"], k["ids"]["service"]) as conn:
        assert conn.execute("SELECT pm_retire_safety_sessions() AS n").fetchone()["n"] == 1
    assert admin.execute("SELECT count(*) FROM escalation_events WHERE id=%s",
                          (message.event_id,)).fetchone()[0] == 0
    assert ack.acknowledge(k["cfg"], token) == "invalid"


def test_uncertain_delivery_remains_pending_and_cannot_retry(kaze_sandbox, admin):
    k = kaze_sandbox
    _, message = prepared(k, admin)
    class Unknown:
        name = "test-timeout"
        calls = 0
        def send(self, message):
            self.calls += 1
            return "pending"
    sender = Unknown()
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "pending"
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "pending"
    assert sender.calls == 1
    assert admin.execute("SELECT delivery FROM escalation_events WHERE id=%s",
                          (message.event_id,)).fetchone()[0] == "pending"
    # Runtime cannot clear the durable claim, even by resetting delivery to pending.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with transaction(k["cfg"], k["ids"]["service"]) as conn:
            conn.execute("UPDATE escalation_events SET delivery_started_at=NULL WHERE id=%s",
                         (message.event_id,))
    sent_at = admin.execute("SELECT sent_at FROM escalation_events WHERE id=%s",
                             (message.event_id,)).fetchone()[0]
    # Uncertainty does not claim acknowledgement or stop the standard next-contact timer.
    assert run_pass(k["cfg"], k["ids"]["service"], sender,
                    now=sent_at + timedelta(minutes=10))[0][1].level == 3
    assert sender.calls == 2
    assert admin.execute("SELECT delivery FROM escalation_events WHERE id=%s",
                          (message.event_id,)).fetchone()[0] == "pending"


def test_expired_session_cannot_begin_delivery(kaze_sandbox, admin):
    k = kaze_sandbox
    sid, message = prepared(k, admin)
    ended = clock(admin) - timedelta(seconds=1)
    admin.execute("UPDATE safety_sessions SET ends_at=%s WHERE id=%s", (ended, sid))
    sender = sms.LogSender(keep=1)
    assert sms.send(k["cfg"], k["ids"]["service"], message, sender) == "failed"
    assert list(sender.outbox) == []
    assert admin.execute("SELECT status,ended_at,delete_after FROM safety_sessions WHERE id=%s",
                          (sid,)).fetchone() == ("ended", ended, ended + timedelta(hours=24))
