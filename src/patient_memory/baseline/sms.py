"""KAZE escalation texts: fixed wording, the sender interface and its two senders (BL-27, decision 023).

The scheduler (BL-26) decides when a ladder step runs. For each SMS step it calls, in order:

1. `prepare_sms(conn, cfg, session, contact_index, level, trigger, at, location)` inside its
   locked transaction. It mints the acknowledgement token, renders the fixed text and inserts the
   `escalation_events` row as `pending`, storing only the token hash and a copy of the text with
   the links replaced. It returns an `OutboundSms`, or None when that step already exists (a
   duplicate pass), so nothing is sent twice.
2. After commit, `send(cfg, identity, outbound, sender)`, which calls `sender.send(outbound)`
   (never raises) and records `logged`, `sent` or `failed` on the row.

Delivery is at most once: a crash between the two steps leaves the row `pending` and visible on
the session page; nothing resends it automatically.

The default sender only logs. `TwilioSender` runs only with `PM_SMS_PROVIDER=twilio`, full
credentials, an HTTPS acknowledgement base URL and an explicit recipient allowlist, and it never
runs in tests or CI. The text never mentions drinks, drugs, intoxication or a diagnosis, and the
service never calls 911 itself: the level-4 text asks the contact to.
"""
import logging
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx

from patient_memory.baseline.ack import ack_link, new_token
from patient_memory.baseline.sessions import mask_phone
from patient_memory.storage import transaction

log = logging.getLogger("patient_memory.kaze.sms")

Delivery = Literal["logged", "sent", "failed"]
DELIVERIES = ("logged", "sent", "failed")
TRIGGERS = ("missed_checkin", "speech_change")

# Fixed wording (docs/06-baseline.md). Only the name, time and links vary.
TEMPLATES = {
    "missed_checkin": "{name} asked us to check on them if they missed a check-in. "
                      "They missed one at {time}. Last location: {location}. "
                      "Tap to say you're on it: {ack}",
    "speech_change": "{name} asked us to check on them if a check-in sounded different from "
                     "earlier tonight. One at {time} did. Last location: {location}. "
                     "Tap to say you're on it: {ack}",
}
LEVEL_4 = " If you can't reach them, call 911."
NO_LOCATION = "not shared"
ACK_PLACEHOLDER = "[ack link]"
LOCATION_PLACEHOLDER = "[location link]"


@dataclass(frozen=True)
class OutboundSms:
    """One text for one escalation row. `body` holds the live ack link and is never stored or
    logged by default; `record` is the stored copy with both links replaced."""

    event_id: UUID
    tenant_id: UUID
    patient_id: UUID
    session_id: UUID
    contact_index: int
    level: int
    to: str = field(repr=False)
    body: str = field(repr=False)
    record: str = field(repr=False)


class SmsSender(Protocol):
    """`send` delivers one text and returns `logged`, `sent` (accepted by the provider, not proof
    of receipt) or `failed`. Implementations should not raise; `deliver` guards anyway."""

    name: str

    def send(self, message: OutboundSms) -> Delivery: ...


def display_name(name: str) -> str:
    """The person's chosen name, with control characters and line breaks removed."""
    kept = "".join(" " if unicodedata.category(c).startswith("C") else c for c in name)
    return " ".join(kept.split())[:40] or "Someone"


def clock_time(at: datetime, tz: str) -> str:
    local = at.astimezone(ZoneInfo(tz))
    return f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"


def location_link(location: tuple[float, float] | None) -> str | None:
    if location is None:
        return None
    lat, lon = location
    return f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lon:.5f}"


def render(trigger: str, level: int, name: str, at: datetime, tz: str,
           location: tuple[float, float] | None, ack_url: str) -> tuple[str, str]:
    """Return (text to send, text to store). Levels 2-4 only; 911 wording only at level 4."""
    if trigger not in TRIGGERS or level not in (2, 3, 4):
        raise ValueError("SMS steps are levels 2-4 with a known trigger")
    place = location_link(location)
    fields = {"name": display_name(name), "time": clock_time(at, tz)}
    suffix = LEVEL_4 if level == 4 else ""
    body = TEMPLATES[trigger].format(**fields, location=place or NO_LOCATION, ack=ack_url) + suffix
    record = TEMPLATES[trigger].format(
        **fields, location=LOCATION_PLACEHOLDER if place else NO_LOCATION,
        ack=ACK_PLACEHOLDER) + suffix
    return body, record


def last_location(conn, patient_id: UUID, session_id: UUID) -> tuple[float, float] | None:
    row = conn.execute(
        "SELECT lat,lon FROM voice_checks WHERE patient_id=%s AND session_id=%s AND lat IS NOT NULL "
        "ORDER BY ts DESC LIMIT 1", (patient_id, session_id)).fetchone()
    return (row["lat"], row["lon"]) if row else None


def prepare_sms(conn, cfg, session, contact_index: int, level: int, trigger: str, at: datetime,
                location: tuple[float, float] | None = None) -> OutboundSms | None:
    """Insert one pending SMS escalation row for the session's current episode.

    `session` is the locked `safety_sessions` row (the scheduler has already set its episode).
    `at` is the missed due time or the check time that triggered the step. Returns None when the
    (session, episode, level, contact) step already exists."""
    pid, sid = session["patient_id"], session["id"]
    if not session["escalation_enabled"] or session["status"] == "ended":
        raise ValueError("This session does not send texts")
    contact = conn.execute(
        "SELECT phone_e164 FROM safety_contacts WHERE patient_id=%s AND session_id=%s "
        "AND contact_index=%s", (pid, sid, contact_index)).fetchone()
    if not contact:
        raise LookupError("No such contact on this session")
    token = new_token()
    body, record = render(trigger, level, session["display_name"], at, cfg.shift_timezone,
                          location, ack_link(cfg.ack_base_url, token.token))
    event_id = uuid4()
    # Expiry: the configured lifetime, never past the session's latest possible deletion time.
    row = conn.execute(
        "INSERT INTO escalation_events(tenant_id,patient_id,id,session_id,episode,level,trigger,"
        "channel,contact_index,delivery,message,ack_token_hash,ack_expires_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'sms',%s,'pending',%s,%s,"
        "LEAST(clock_timestamp() + make_interval(mins => %s), "
        "%s::timestamptz + interval '24 hours')) ON CONFLICT DO NOTHING RETURNING id",
        (session["tenant_id"], pid, event_id, sid, session["episode"], level, trigger,
         contact_index, record, token.digest, cfg.ack_ttl_min, session["ends_at"])).fetchone()
    if not row:
        return None
    return OutboundSms(event_id, session["tenant_id"], pid, sid, contact_index, level,
                       contact["phone_e164"], body, record)


def deliver(sender: SmsSender, message: OutboundSms) -> Delivery:
    try:
        result = sender.send(message)
    except Exception:  # a sender bug must not stop the ladder from recording the step
        log.exception("sms sender=%s event=%s raised", sender.name, message.event_id)
        return "failed"
    return result if result in DELIVERIES else "failed"


def record_delivery(conn, message: OutboundSms, delivery: Delivery) -> bool:
    return conn.execute(
        "UPDATE escalation_events SET delivery=%s WHERE patient_id=%s AND id=%s "
        "AND delivery='pending'", (delivery, message.patient_id, message.event_id)).rowcount == 1


def send(cfg, identity, message: OutboundSms, sender: SmsSender | None = None) -> Delivery:
    """Send after the step's row is committed, then record the outcome as `identity`."""
    delivery = deliver(sender or sender_for(cfg), message)
    with transaction(cfg, identity) as conn:
        record_delivery(conn, message, delivery)
    return delivery


class LogSender:
    """Default sender: logs the stored copy (links replaced) and keeps a short in-memory outbox.
    With `log_links` (PM_SMS_LOG_LINKS, local synthetic demos only) it logs the live text so a
    presenter can open the ack link without a phone."""

    name = "log"

    def __init__(self, log_links: bool = False, keep: int = 50):
        self.log_links = log_links
        self.outbox: deque[OutboundSms] = deque(maxlen=keep)

    def send(self, message: OutboundSms) -> Delivery:
        self.outbox.append(message)
        log.info("sms logged event=%s level=%d to=%s text=%s", message.event_id, message.level,
                 mask_phone(message.to), message.body if self.log_links else message.record)
        return "logged"


class TwilioSender:
    """Twilio Programmable Messaging. Sends only to numbers on the explicit allowlist; the
    response body (which echoes the number and text) is never logged."""

    name = "twilio"
    API = "https://api.twilio.com"

    def __init__(self, account_sid: str, auth_token: str, sender: str, allowed: frozenset[str],
                 client: httpx.Client | None = None):
        self.account_sid, self.sender, self.allowed = account_sid, sender, allowed
        self.client = client or httpx.Client(timeout=10.0, follow_redirects=False)
        self.auth = httpx.BasicAuth(account_sid, auth_token)

    def __repr__(self):
        return f"TwilioSender(allowed={len(self.allowed)})"

    def send(self, message: OutboundSms) -> Delivery:
        if message.to not in self.allowed:
            log.warning("sms refused event=%s: recipient %s is not on PM_SMS_ALLOWED_RECIPIENTS",
                        message.event_id, mask_phone(message.to))
            return "failed"
        origin = ("MessagingServiceSid" if self.sender.startswith("MG") else "From")
        try:
            response = self.client.post(
                f"{self.API}/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                data={"To": message.to, origin: self.sender, "Body": message.body},
                auth=self.auth)
        except httpx.HTTPError as exc:
            log.warning("sms twilio event=%s transport error %s", message.event_id,
                        type(exc).__name__)
            return "failed"
        if 200 <= response.status_code < 300:
            log.info("sms twilio event=%s accepted to=%s", message.event_id,
                     mask_phone(message.to))
            return "sent"
        log.warning("sms twilio event=%s rejected status=%d", message.event_id,
                    response.status_code)
        return "failed"


def allowed_recipients(raw: str) -> frozenset[str]:
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def sender_for(cfg) -> SmsSender:
    if cfg.sms_provider == "twilio":
        return TwilioSender(cfg.twilio_sid, cfg.twilio_token, cfg.twilio_from,
                            allowed_recipients(cfg.sms_allowed_recipients))
    return LogSender(cfg.sms_log_links)
