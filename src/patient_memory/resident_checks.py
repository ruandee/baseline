"""PSW-facing check workflow (BL-31, decision 017): due list, skips and consent records.

Nothing here reads assessments, verdicts or features: the responses are score-free by
construction, so a PSW device never receives a score.
"""
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg.errors import InsufficientPrivilege

from patient_memory.config import Settings
from patient_memory.consent import check_gate, consent_record
from patient_memory.domain import ConsentInput, SkipInput
from patient_memory.errors import Problem
from patient_memory.ingestion import lock_patient
from patient_memory.storage import audit, require_member


def day_start(now: datetime, timezone: str) -> datetime:
    local = now.astimezone(ZoneInfo(timezone))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def due_checks(conn, cfg: Settings, now: datetime | None = None) -> dict:
    require_member(conn)
    start = day_start(now or datetime.now(UTC), cfg.shift_timezone)
    rows = conn.execute(
        "SELECT p.id, p.external_id,"
        " pm_last_check_at(p.id) AS last_check_ts,"
        " EXISTS(SELECT FROM check_skips s WHERE s.tenant_id=p.tenant_id AND s.patient_id=p.id"
        "  AND s.recorded_at>=%s) AS skipped_today"
        " FROM patients p WHERE pm_checker(p.id) ORDER BY p.external_id, p.id", (start,)).fetchall()
    residents = []
    for row in rows:
        state = consent_record(conn, row["id"])["state"]
        last = row["last_check_ts"]
        status = ("consent_needed" if state != "granted"
                  else "done" if last and last >= start
                  else "skipped" if row["skipped_today"] else "due")
        residents.append({"patient_id": row["id"], "display_name": row["external_id"],
                          "status": status, "consent_state": state, "last_check_ts": last,
                          "skipped_today": row["skipped_today"], "observation_helped": None})
    return {"day_start": start, "residents": residents}


def record_skip(conn, identity, patient_id: UUID, body: SkipInput, request_id: UUID) -> dict:
    """A skip is not a consent decision: a resident declining today does not withdraw consent."""
    check_gate(conn, patient_id)
    skip_id = uuid4()
    recorded_at = conn.execute(
        "INSERT INTO check_skips(tenant_id,patient_id,id,reason,device_ts,recorded_by)"
        " VALUES(%s,%s,%s,%s,%s,%s) RETURNING recorded_at",
        (identity.tenant_id, patient_id, skip_id, body.reason, body.device_ts,
         identity.principal_id)).fetchone()["recorded_at"]
    audit(conn, identity, patient_id, "check_skipped", request_id)
    return {"skip_id": skip_id, "recorded_at": recorded_at}


def has_role(conn, patient_id: UUID, role: str) -> bool:
    return conn.execute("SELECT pm_role(%s,%s) AS ok", (patient_id, role)).fetchone()["ok"]


def append_consent(conn, identity, patient_id: UUID, body: ConsentInput, request_id: UUID) -> dict:
    """Nurses record resident/SDM decisions; importers may write explicit fixture consent."""
    check_gate(conn, patient_id)
    lock_patient(conn, patient_id)
    check_gate(conn, patient_id)
    if body.decided_by == "synthetic_fixture":
        allowed = has_role(conn, patient_id, "importer")
    else:
        allowed = has_role(conn, patient_id, "nurse")
    if not allowed:
        raise Problem(403, "forbidden", "This role cannot record that consent decision")
    try:
        conn.execute(
            "INSERT INTO resident_consents(tenant_id,patient_id,id,scope,status,decided_by,"
            "sdm_reference,expires_at,note,recorded_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (identity.tenant_id, patient_id, uuid4(), body.scope, body.status, body.decided_by,
             body.sdm_reference, body.expires_at, body.note, identity.principal_id))
    except InsufficientPrivilege as exc:  # RLS agrees with the checks above; belt and braces
        raise Problem(403, "forbidden", "This role cannot record that consent decision") from exc
    audit(conn, identity, patient_id, f"consent_{body.status}", request_id)
    return consent_record(conn, patient_id, body.scope)


def watchlist_allowed(conn) -> bool:
    """PSW-only principals never read the watch list (scores, verdicts, sparklines)."""
    row = conn.execute(
        "SELECT EXISTS(SELECT FROM assignments WHERE principal_id=pm_actor() AND active"
        " AND role='psw') AS psw, EXISTS(SELECT FROM assignments WHERE principal_id=pm_actor()"
        " AND active AND role IN ('nurse','importer')) AS care").fetchone()
    return row["care"] or not row["psw"]
