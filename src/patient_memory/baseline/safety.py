"""KAZE scheduler: missed check-ins, speech-change trigger and the escalation ladder (BL-26).

Decision 018 fixes the session states, timings and check-in reset rule. Everything time-dependent takes an explicit `now`
so tests drive a deterministic clock; in the worker `now` is the database clock, the same clock
that stamps check-ins and `next_due_at`.

The ladder never dials anyone and never diagnoses. Level 4's text (BL-27) tells contacts to call
911 themselves if they cannot reach the person.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from patient_memory.ingestion import lock_patient
from patient_memory.storage import transaction

log = logging.getLogger("patient_memory.safety")

PASS_EVERY_S = 15
TRIGGERS = ("missed_checkin", "speech_change")
SPEECH_STATUSES = ("change", "provisional")
ACK_TTL_BOUND = timedelta(hours=24)  # an ack link never outlives the session's retention window


@dataclass(frozen=True)
class Timing:
    """Offsets of the ladder. Level 0 (the on-page buzz at `next_due_at`) is client side."""
    nudge: timedelta  # level 1: this long after the check was due
    sms: timedelta    # level 2: this long after the check was due
    step: timedelta   # levels 3 and 4: this long after the previous level, with no ack


# docs/06-baseline.md, unchanged. This is the only timing outside an explicit demo setting.
STANDARD = Timing(nudge=timedelta(minutes=2, seconds=30), sms=timedelta(minutes=5),
                  step=timedelta(minutes=10))
def timing_for(cfg) -> Timing:
    return STANDARD


# ---------------------------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionState:
    status: str
    ends_at: datetime
    next_due_at: datetime | None
    ladder_level: int
    episode: int
    ladder_trigger: str | None
    escalation_enabled: bool
    contacts: tuple[int, ...]  # contact indexes present, e.g. (1,) or (1, 2)


@dataclass(frozen=True)
class Step:
    level: int
    trigger: str
    episode: int
    status: str                   # session status after the step
    contacts: tuple[int, ...]     # empty for the level-1 nudge


def speech_trigger(change_status: str | None, explainers: list[str] | tuple[str, ...]) -> bool:
    """A sharp change from tonight's baseline that no session explainer covers."""
    return change_status in SPEECH_STATUSES and not explainers


def level_contacts(level: int, contacts: tuple[int, ...]) -> tuple[int, ...]:
    if level == 1:
        return ()
    if level == 2:
        return contacts[:1]
    if level == 3:
        return (2,) if 2 in contacts else contacts[:1]
    return contacts


def plan(s: SessionState, now: datetime, timing: Timing, speech: bool,
         last_step_at: datetime | None) -> Step | None:
    """The next ladder step for a session at `now`, or None. At most one level per pass, so each
    contact gets the full `step` window before the next contact is texted.

    - Only `active` and `escalating` progress; `arming`, `acknowledged` and `ended` are frozen.
    - Past `ends_at` the session is expired: nothing more is sent (retention marks it ended).
    - Levels 1-2 come from how overdue the check-in is, or a speech-change trigger (straight to 2).
    - Levels 3-4 come `step` after the previous level was executed.
    - `escalation_enabled = false` caps the ladder at the level-1 nudge.
    """
    if s.status not in ("active", "escalating") or s.next_due_at is None or now >= s.ends_at:
        return None
    cap = 4 if s.escalation_enabled else 1
    level = s.ladder_level
    if level >= cap:
        return None
    if level <= 1:
        overdue = now - s.next_due_at
        if speech:
            target, trigger = 2, "speech_change"
        elif overdue >= timing.sms:
            target, trigger = 2, "missed_checkin"
        elif overdue >= timing.nudge:
            target, trigger = 1, "missed_checkin"
        else:
            return None
        target = min(target, cap)
        if target <= level:
            return None
    else:
        if last_step_at is None or now - last_step_at < timing.step:
            return None
        target, trigger = level + 1, s.ladder_trigger or "missed_checkin"
    return Step(level=target, trigger=trigger,
                episode=s.episode + 1 if level == 0 else s.episode,
                status="escalating" if target >= 2 else "active",
                contacts=level_contacts(target, s.contacts))


def checkin_update(status: str, usable: bool, is_baseline: bool, change_status: str | None,
                   explainers: list[str] | tuple[str, ...], ts: datetime, interval_min: int) -> dict | None:
    """Session fields a stored check-in changes (decision 018 transitions, decision 018 rule).

    A usable check-in that is not an unexplained change resets the ladder and restarts the timer
    from the check's server time, in `active`, `escalating` or `acknowledged`. An unusable clip
    is not a check-in. An unexplained change/provisional check-in does not reset: it is the
    speech-change trigger, which the next pass turns into level 2."""
    if not usable or is_baseline or status not in ("active", "escalating", "acknowledged"):
        return None
    if speech_trigger(change_status, explainers):
        return None
    return {"status": "active", "ladder_level": 0, "ladder_trigger": None,
            "next_due_at": ts + timedelta(minutes=interval_min)}


# ---------------------------------------------------------------------------------------------
# Sender interface (implemented by BL-27, #29)
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Location:
    lat: float
    lon: float
    accuracy_m: float | None


@dataclass(frozen=True)
class OutboundEvent:
    """One `escalation_events` row (channel 'sms', delivery 'pending') to deliver."""
    event_id: UUID
    tenant_id: UUID
    patient_id: UUID
    session_id: UUID
    episode: int
    level: int
    trigger: str
    contact_index: int
    contact_name: str
    phone_e164: str
    display_name: str
    missed_at: datetime  # the missed check's due time, or the triggering check's time
    last_location: Location | None
    sent_at: datetime
    ack_expires_max: datetime


@dataclass(frozen=True)
class Delivery:
    status: Literal["logged", "sent", "failed"]
    message: str | None = None          # text as sent, ack link replaced by "[ack link]"
    ack_token_hash: bytes | None = None  # sha256 of the token; the raw token is never returned
    ack_expires_at: datetime | None = None


class Sender(Protocol):
    """Offline preparation only, under the patient/session locks. No network or database calls.

    BL-27 must replace this adapter with prepare/commit/deliver before enabling real delivery.
    The scheduler inserts returned immutable message/hash fields once, never updates them.
    """

    def send(self, event: OutboundEvent) -> Delivery: ...


def mask(phone: str) -> str:
    return phone[:1] + "*" * max(len(phone) - 5, 0) + phone[-4:]


class LogSender:
    """Default until BL-27: logs the step without the phone number or location; no ack token."""

    def send(self, event: OutboundEvent) -> Delivery:
        log.info("kaze escalation session=%s episode=%s level=%s contact=%s phone=%s trigger=%s",
                 event.session_id, event.episode, event.level, event.contact_index,
                 mask(event.phone_e164), event.trigger)
        return Delivery("logged", message=f"[stub] level {event.level} text to contact "
                                          f"{event.contact_index}")


def sender_from_settings(cfg) -> Sender:
    """BL-27 returns its Twilio sender (or log fallback) here."""
    return LogSender()


def checked_delivery(result, event: OutboundEvent) -> Delivery:
    """Reject anything the escalation_events constraints or the ack contract would not accept."""
    if not isinstance(result, Delivery) or result.status not in ("logged", "sent", "failed"):
        return Delivery("failed")
    token, expires = result.ack_token_hash, result.ack_expires_at
    if (token is None) != (expires is None):
        return Delivery("failed", result.message)
    if token is not None and (not isinstance(token, bytes) or len(token) != 32
                              or expires > event.ack_expires_max or expires <= event.sent_at):
        return Delivery("failed", result.message)
    return result


# ---------------------------------------------------------------------------------------------
# Database pass
# ---------------------------------------------------------------------------------------------

def _speech(conn, pid: UUID, sid: UUID, explainers: list[str]) -> tuple[bool, datetime | None]:
    """Is the latest usable session check-in an unexplained change? Stateless: a later normal
    check-in becomes the latest one and clears it, so repeated passes agree."""
    row = conn.execute(
        "SELECT v.ts,a.change_status FROM voice_checks v LEFT JOIN assessments a "
        "ON a.tenant_id=v.tenant_id AND a.patient_id=v.patient_id AND a.check_id=v.id "
        "WHERE v.patient_id=%s AND v.session_id=%s AND v.usable AND NOT v.is_baseline "
        "ORDER BY v.ts DESC LIMIT 1", (pid, sid)).fetchone()
    if row is None:
        return False, None
    return speech_trigger(row["change_status"], explainers), row["ts"]


def _last_location(conn, pid: UUID, sid: UUID) -> Location | None:
    row = conn.execute(
        "SELECT lat,lon,accuracy_m FROM voice_checks WHERE patient_id=%s AND session_id=%s "
        "AND lat IS NOT NULL ORDER BY ts DESC LIMIT 1", (pid, sid)).fetchone()
    return Location(row["lat"], row["lon"], row["accuracy_m"]) if row else None


def advance(conn, pid: UUID, sid: UUID, now: datetime | None, timing: Timing,
            sender: Sender) -> Step | None:
    """One session, one transaction: lock, plan, record, send. Lock order matches check
    admission's patient lock and `pm_acknowledge_escalation`'s session row lock."""
    lock_patient(conn, pid)
    row = conn.execute("SELECT * FROM safety_sessions WHERE patient_id=%s AND id=%s FOR UPDATE",
                       (pid, sid)).fetchone()
    if row is None:
        return None
    # Evaluate expiry after waiting for both locks, never with the pass's stale clock.
    if now is None:
        now = conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]
    if row["status"] != "ended" and now >= row["ends_at"]:
        conn.execute(
            "UPDATE safety_sessions SET status='ended',ended_at=ends_at,end_reason='expired',"
            "delete_after=ends_at+interval '24 hours',next_due_at=NULL WHERE patient_id=%s AND id=%s",
            (pid, sid))
        return None
    contacts = {c["contact_index"]: c for c in conn.execute(
        "SELECT contact_index,name,phone_e164 FROM safety_contacts WHERE patient_id=%s "
        "AND session_id=%s ORDER BY contact_index", (pid, sid)).fetchall()}
    state = SessionState(row["status"], row["ends_at"], row["next_due_at"], row["ladder_level"],
                         row["episode"], row["ladder_trigger"], row["escalation_enabled"],
                         tuple(contacts))
    speech, speech_at = _speech(conn, pid, sid, row["context_tags"])
    last_step_at = conn.execute(
        "SELECT max(sent_at) AS t FROM escalation_events WHERE patient_id=%s AND session_id=%s "
        "AND episode=%s AND level=%s", (pid, sid, state.episode, state.ladder_level)
    ).fetchone()["t"] if state.ladder_level >= 2 else None
    step = plan(state, now, timing, speech, last_step_at)
    if step is None:
        return None
    if step.level >= 2 and not step.contacts:
        log.warning("kaze session %s has no contacts; ladder cannot text", sid)
        return None
    conn.execute(
        "UPDATE safety_sessions SET status=%s,ladder_level=%s,ladder_trigger=%s,episode=%s "
        "WHERE patient_id=%s AND id=%s",
        (step.status, step.level, step.trigger, step.episode, pid, sid))
    base = (row["tenant_id"], pid, sid, step.episode, step.level, step.trigger)
    if step.level == 1:
        conn.execute(
            "INSERT INTO escalation_events(tenant_id,patient_id,session_id,episode,level,trigger,"
            "id,channel,contact_index,sent_at,delivery) VALUES(%s,%s,%s,%s,%s,%s,%s,'nudge',NULL,"
            "%s,'logged') ON CONFLICT DO NOTHING", (*base, uuid4(), now))
        return step
    location = _last_location(conn, pid, sid)
    missed_at = speech_at if step.trigger == "speech_change" and speech_at else row["next_due_at"]
    for index in step.contacts:
        event_id = uuid4()
        contact = contacts[index]
        event = OutboundEvent(
            event_id=event_id, tenant_id=row["tenant_id"], patient_id=pid, session_id=sid,
            episode=step.episode, level=step.level, trigger=step.trigger, contact_index=index,
            contact_name=contact["name"], phone_e164=contact["phone_e164"],
            display_name=row["display_name"], missed_at=missed_at, last_location=location,
            sent_at=now, ack_expires_max=row["ends_at"] + ACK_TTL_BOUND)
        try:
            delivery = checked_delivery(sender.send(event), event)
        except Exception:  # a sender failure is recorded, never allowed to stall other sessions
            log.exception("kaze sender failed for session %s level %s", sid, step.level)
            delivery = Delivery("failed")
        conn.execute(
            "INSERT INTO escalation_events(tenant_id,patient_id,session_id,episode,level,trigger,"
            "id,channel,contact_index,sent_at,delivery,message,ack_token_hash,ack_expires_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,'sms',%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (*base, event_id, index, now, delivery.status, delivery.message,
             delivery.ack_token_hash, delivery.ack_expires_at))
    return step


def run_pass(cfg, identity, sender: Sender | None = None, now: datetime | None = None,
             timing: Timing | None = None) -> list[tuple[UUID, Step]]:
    """Advance every open session visible to `identity` (the kaze-service principal). Each
    session commits separately; a failing session is logged and retried next pass."""
    sender = sender or sender_from_settings(cfg)
    timing = timing or timing_for(cfg)
    with transaction(cfg, identity) as conn:
        due = conn.execute(
            "SELECT patient_id,id FROM safety_sessions WHERE status IN ('active','escalating') "
            "AND next_due_at IS NOT NULL ORDER BY next_due_at").fetchall()
    steps = []
    for r in due:
        try:
            with transaction(cfg, identity) as conn:
                step = advance(conn, r["patient_id"], r["id"], now, timing, sender)
        except Exception:
            log.exception("kaze scheduler failed for session %s", r["id"])
            continue
        if step:
            steps.append((r["id"], step))
    return steps
