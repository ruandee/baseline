"""KAZE safety sessions: arm, status, end, session check-ins and retention (decision 018).

Ladder progression (nudges, SMS, speech-change trigger, check-in resets) belongs to BL-26; this
module owns the session record, the arming -> active transition and the end/retention lifecycle.
"""
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import psycopg

from patient_memory.domain import SessionArm, SessionOut, SessionSummary
from patient_memory.errors import Problem
from patient_memory.ingestion import idempotent, lock_patient
from patient_memory.storage import audit, patient_access, transaction

BASELINE_REQUIRED = 3
MAX_DURATION = timedelta(hours=24)
RETENTION = timedelta(hours=24)
OPEN = ("arming", "active", "escalating", "acknowledged")


def window_error(created_at: datetime, ends_at: datetime, interval_min: int) -> str | None:
    """A session must last at least one check-in interval and at most 24 h from arming."""
    if ends_at < created_at + timedelta(minutes=interval_min):
        return "ends_at must be at least one interval after arming"
    if ends_at > created_at + MAX_DURATION:
        return "ends_at must be within 24 hours of arming"
    return None


def activation(status: str, usable_baselines: int, required: int, ts: datetime,
               interval_min: int) -> dict | None:
    """The only ladder transition owned by BL-25: arming -> active on the last baseline clip."""
    if status != "arming" or usable_baselines < required:
        return None
    return {"status": "active", "activated_at": ts,
            "next_due_at": ts + timedelta(minutes=interval_min)}


def mask_phone(phone: str) -> str:
    return phone[:1] + "*" * (len(phone) - 5) + phone[-4:]


def check_problem(status: str, mode: str, is_baseline: bool,
                  past_end: bool = False) -> Problem | None:
    """Which check-ins a session accepts in each state. A session past `ends_at` is over even
    before the retention job marks it expired."""
    if status == "ended" or past_end:
        return Problem(409, "session_ended")
    if mode != "live":
        return Problem(422, "invalid_request", "Session check-ins use mode live")
    if (status == "arming") != bool(is_baseline):
        return Problem(422, "invalid_request",
                       "Arming takes baseline clips only; an armed session takes check-ins only")
    return None


def safety_tenant(conn) -> bool:
    return conn.execute("SELECT pm_safety_tenant() AS ok").fetchone()["ok"]


def owner_gate(conn, patient_id: UUID):
    """Arm, end and check in: only the person themselves (importer on their own row) in a
    safety-mode tenant. Everyone else gets 404."""
    patient = patient_access(conn, patient_id, write=True)
    if not safety_tenant(conn):
        raise Problem(404, "not_found")
    return patient


def reader_gate(conn, patient_id: UUID):
    """Status: the person and the kaze-service care-team principal."""
    patient = patient_access(conn, patient_id)
    if not safety_tenant(conn) or not conn.execute(
            "SELECT pm_care(%s) AS ok", (patient_id,)).fetchone()["ok"]:
        raise Problem(404, "not_found")
    return patient


def _row(conn, patient_id: UUID, session_id: UUID, lock=False):
    row = conn.execute("SELECT * FROM safety_sessions WHERE patient_id=%s AND id=%s"
                       + (" FOR UPDATE" if lock else ""), (patient_id, session_id)).fetchone()
    if not row:
        raise Problem(404, "not_found")
    # Sample expiry after FOR UPDATE has actually acquired the row lock. A computed SELECT
    # column can otherwise be evaluated before waiting for a concurrent session mutation.
    row["past_end"] = conn.execute("SELECT %s<=clock_timestamp() AS past_end",
                                   (row["ends_at"],)).fetchone()["past_end"]
    return row


def _usable_baselines(conn, patient_id: UUID, session_id: UUID) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM voice_checks WHERE patient_id=%s AND session_id=%s "
        "AND is_baseline AND usable", (patient_id, session_id)).fetchone()["n"]


def summary(conn, row) -> SessionSummary:
    return SessionSummary(id=row["id"], status=row["status"],
                          baseline_required=row["baseline_required"],
                          baseline_usable=_usable_baselines(conn, row["patient_id"], row["id"]),
                          next_due_at=row["next_due_at"])


def describe(conn, row, detail=True) -> SessionOut:
    pid, sid = row["patient_id"], row["id"]
    contacts = conn.execute(
        "SELECT contact_index,name,phone_e164 FROM safety_contacts WHERE patient_id=%s "
        "AND session_id=%s ORDER BY contact_index", (pid, sid)).fetchall()
    checks = escalations = []
    if detail:
        checks = conn.execute(
            "SELECT v.id,v.ts,v.usable,v.is_baseline,v.lat IS NOT NULL AS has_location,"
            "(SELECT a.change_status FROM assessments a WHERE a.tenant_id=v.tenant_id "
            "AND a.patient_id=v.patient_id AND a.check_id=v.id LIMIT 1) AS change_status "
            "FROM voice_checks v WHERE v.patient_id=%s AND v.session_id=%s ORDER BY v.ts",
            (pid, sid)).fetchall()
        escalations = conn.execute(
            "SELECT id,episode,level,trigger,channel,contact_index,sent_at,delivery,message,ack_at "
            "FROM escalation_events WHERE patient_id=%s AND session_id=%s "
            "ORDER BY sent_at,level,contact_index NULLS FIRST", (pid, sid)).fetchall()
    fields = {k: row[k] for k in SessionOut.model_fields if k in row}
    return SessionOut(
        **fields,
        baseline={"required": row["baseline_required"],
                  "usable": _usable_baselines(conn, pid, sid)},
        contacts=[{"contact_index": c["contact_index"], "name": c["name"],
                   "phone_masked": mask_phone(c["phone_e164"])} for c in contacts],
        checks=checks, escalations=escalations)


def arm(conn, identity, patient_id: UUID, body: SessionArm, key: str | None,
        request_id: UUID) -> dict:
    owner_gate(conn, patient_id)

    def perform():
        created_at = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
        problem = window_error(created_at, body.ends_at, body.interval_min)
        if problem:
            raise Problem(422, "invalid_request", problem)
        # A previous session past its end is over even if retention has not run yet.
        conn.execute(
            "UPDATE safety_sessions SET status='ended',end_reason='expired',ended_at=ends_at,"
            "delete_after=ends_at+%s,next_due_at=NULL WHERE patient_id=%s AND status<>'ended' "
            "AND ends_at<=clock_timestamp()", (RETENTION, patient_id))
        if conn.execute("SELECT 1 FROM safety_sessions WHERE patient_id=%s AND status<>'ended'",
                        (patient_id,)).fetchone():
            raise Problem(409, "session_open")
        sid = uuid4()
        try:
            conn.execute(
                "INSERT INTO safety_sessions(tenant_id,patient_id,id,display_name,created_at,"
                "ends_at,interval_min,context_tags,escalation_enabled,baseline_required) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, patient_id, sid, body.display_name, created_at,
                 body.ends_at, body.interval_min, list(body.context_tags),
                 body.escalation_enabled, BASELINE_REQUIRED))
        except psycopg.errors.UniqueViolation as exc:
            raise Problem(409, "session_open") from exc
        for index, contact in enumerate(body.contacts, start=1):
            conn.execute(
                "INSERT INTO safety_contacts(tenant_id,patient_id,session_id,contact_index,name,"
                "phone_e164) VALUES(%s,%s,%s,%s,%s,%s)",
                (identity.tenant_id, patient_id, sid, index, contact.name, contact.phone_e164))
        audit(conn, identity, patient_id, "arm_session", request_id)
        return describe(conn, _row(conn, patient_id, sid)).model_dump(mode="json")

    if key is None:
        lock_patient(conn, patient_id)
        return perform()
    return idempotent(conn, identity, patient_id, "arm_session", key,
                      body.model_dump(mode="json"), perform)


def end(conn, identity, patient_id: UUID, session_id: UUID, request_id: UUID) -> SessionOut:
    owner_gate(conn, patient_id)
    row = _row(conn, patient_id, session_id, lock=True)
    if row["status"] != "ended":
        # A late end request cannot extend the retention window past the planned expiry.
        ended_at = (row["ends_at"] if row["past_end"] else
                    conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"])
        reason = "expired" if row["past_end"] else "user"
        conn.execute(
            "UPDATE safety_sessions SET status='ended',end_reason=%s,ended_at=%s,"
            "delete_after=%s,next_due_at=NULL WHERE patient_id=%s AND id=%s",
            (reason, ended_at, ended_at + RETENTION, patient_id, session_id))
        audit(conn, identity, patient_id, "end_session", request_id)
        row = _row(conn, patient_id, session_id)
    return describe(conn, row)


def status(conn, patient_id: UUID, session_id: UUID) -> SessionOut:
    reader_gate(conn, patient_id)
    return describe(conn, _row(conn, patient_id, session_id))


def sessions(conn, patient_id: UUID) -> list[SessionOut]:
    reader_gate(conn, patient_id)
    rows = conn.execute("SELECT * FROM safety_sessions WHERE patient_id=%s ORDER BY created_at DESC",
                        (patient_id,)).fetchall()
    return [describe(conn, r, detail=False) for r in rows]


def check_gate(conn, patient_id: UUID, session_id: UUID, mode: str, is_baseline: bool,
               lock=False):
    """Run before any audio work and again under lock before the insert."""
    owner_gate(conn, patient_id)
    row = _row(conn, patient_id, session_id, lock=lock)
    problem = check_problem(row["status"], mode, is_baseline, row["past_end"])
    if problem:
        raise problem
    return row


def after_check(conn, row, ts: datetime, usable: bool, is_baseline: bool) -> SessionSummary:
    """Record a stored session check: activate on the last baseline clip, note usable check-ins.
    Ladder resets on check-in are BL-26's (decision 018)."""
    pid, sid = row["patient_id"], row["id"]
    if usable and is_baseline:
        change = activation(row["status"], _usable_baselines(conn, pid, sid),
                            row["baseline_required"], ts, row["interval_min"])
        if change:
            conn.execute("UPDATE safety_sessions SET status=%s,activated_at=%s,next_due_at=%s "
                         "WHERE patient_id=%s AND id=%s",
                         (change["status"], change["activated_at"], change["next_due_at"],
                          pid, sid))
    elif usable:
        conn.execute("UPDATE safety_sessions SET last_checkin_at=%s WHERE patient_id=%s AND id=%s",
                     (ts, pid, sid))
    return summary(conn, _row(conn, pid, sid))


def retire(cfg, identity) -> int:
    """Expire past-end sessions and delete those 24 h past their end, within the caller's tenant."""
    with transaction(cfg, identity) as conn:
        return conn.execute("SELECT pm_retire_safety_sessions() AS n").fetchone()["n"]
