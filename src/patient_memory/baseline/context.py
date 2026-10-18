"""Structured context rules (docs/06-baseline.md, "Structured context"). No model involved."""
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from patient_memory.domain import ContextInput, ContextTagOut, Record, SourceInput
from patient_memory.errors import Problem
from patient_memory.extraction import Candidate, extract, fact_id, store_facts, store_relations
from patient_memory.ingestion import bump, submit

HIGH_RISK_MEDICATIONS = ("oxybutynin", "diphenhydramine", "hydroxyzine", "lorazepam", "oxycodone",
                         "hydromorphone", "quetiapine", "haloperidol")
FEVER_C = 37.8
CONTEXT_PREFIX = "context."

# tag -> (kind, default validity window). None means "as recorded" or "that check only".
TAXONOMY = {
    "exertion": ("explainer", None),
    "dentures": ("explainer", timedelta(days=7)),
    "hearing_aid": ("explainer", timedelta(hours=24)),
    "poor_sleep": ("explainer", timedelta(hours=24)),
    "language_change": ("explainer", None),
    "high_risk_med_new": ("amplifier", timedelta(days=7)),
    "fever_documented": ("amplifier", timedelta(hours=48)),
    "poor_intake": ("amplifier", timedelta(hours=48)),
    "recent_fall": ("amplifier", timedelta(days=7)),
    "returned_from_hospital": ("amplifier", timedelta(days=7)),
    "new_confusion_noted": ("amplifier", timedelta(hours=48)),
}


@dataclass
class ContextTag:
    kind: str
    tag: str
    quote: str
    start: int
    end: int
    valid_from: datetime
    valid_to: datetime | None
    candidate: Candidate
    extracted_by: str = "structured"


def default_valid_to(tag, valid_from):
    window = TAXONOMY[tag][1]
    return valid_from + window if window else None


def is_high_risk(text):
    words = set(re.findall(r"[a-z]+", text.casefold()))
    return any(drug in words for drug in HIGH_RISK_MEDICATIONS)


def is_fever(c):
    try:
        value = float(c.value)
    except ValueError:
        return False
    return c.concept == "temperature_c" and math.isfinite(value) and value >= FEVER_C


def matching_tag(source: SourceInput, c):
    # Only affirmed records count: "oxybutynin not given" is not an active order.
    if c.polarity != "present":
        return None
    if (source.kind == "medication_event" and c.event_type in {"ordered", "administered"}
            and (is_high_risk(c.concept) or is_high_risk(c.value))):
        return "high_risk_med_new"
    if source.kind == "observation":
        if is_fever(c):
            return "fever_documented"
        tag = c.concept.removeprefix(CONTEXT_PREFIX)
        # Language mismatch is evidence about one check, never a resident-wide interval.
        # Generic sources have no check identity; leave this for check metadata handling.
        if c.concept.startswith(CONTEXT_PREFIX) and tag in TAXONOMY and tag != "language_change":
            return tag
    return None


def structured_tags(source: SourceInput, candidates):
    tags = []
    for c in candidates:
        tag = matching_tag(source, c)
        if tag:
            valid_from = c.valid_from or source.recorded_at
            # Only a context record carries its own window; the rest use the taxonomy window.
            recorded = c.concept.startswith(CONTEXT_PREFIX) and c.valid_to
            tags.append(ContextTag(TAXONOMY[tag][0], tag, c.quote, c.start, c.end, valid_from,
                                   c.valid_to if recorded else default_valid_to(tag, valid_from), c))
    return tags


def add_context(conn, identity, patient_id, body: ContextInput, key, objects):
    """POST /context: an observation source through normal ingestion plus its structured tag."""
    if (body.tag not in TAXONOMY or TAXONOMY[body.tag][0] != body.kind
            or body.tag == "language_change"):
        raise Problem(422, "invalid_request")
    key = key or str(uuid4())
    source = SourceInput(
        external_document_id="context-" + hashlib.sha256(key.encode()).hexdigest()[:32],
        external_version_id="1", source_system="baseline-context", kind="observation",
        author_role="system", recorded_at=body.valid_from, effective_from=body.valid_from,
        records=[Record(concept=CONTEXT_PREFIX + body.tag, value=body.label,
                        effective_from=body.valid_from, effective_to=body.valid_to)])
    submitted = submit(conn, identity, patient_id, source, key, objects)
    source_id = UUID(submitted["source_version_id"])
    # A replayed key returns the original result even after the source is gone.
    state = conn.execute("SELECT retracted_at,purged_at,published_at FROM sources WHERE id=%s",
                         (source_id,)).fetchone()
    if state["purged_at"] or state["retracted_at"]:
        raise Problem(409, "source_purged" if state["purged_at"] else "source_retracted")
    canonical, candidates = extract(source)
    (tag,) = structured_tags(source, candidates)
    if state["published_at"] is None:
        # submit holds the patient lock through commit. Publish evidence and its tag together,
        # and complete the queued job so a worker cannot publish or bump this source twice.
        store_facts(conn, identity.tenant_id, patient_id, source_id, candidates)
        conn.execute(
            "UPDATE sources SET canonical_text=%s,published_at=clock_timestamp() WHERE id=%s",
            (canonical, source_id))
        store_tags(conn, identity.tenant_id, patient_id, source_id, [tag])
        store_relations(conn, patient_id)
        conn.execute(
            "UPDATE jobs SET status='completed',stage='published',lease_until=NULL,"
            "lease_token=NULL,error_code=NULL "
            "WHERE source_id=%s", (source_id,))
        bump(conn, patient_id)
    return ContextTagOut(
        id=tag_id(source_id, tag), kind=tag.kind, tag=tag.tag, label=body.label, quote=tag.quote,
        start_offset=tag.start, end_offset=tag.end, source_id=source_id,
        valid_from=tag.valid_from.astimezone(UTC),
        valid_to=tag.valid_to.astimezone(UTC) if tag.valid_to else None, extracted_by="structured")


def tag_id(source_id, tag: ContextTag):
    return uuid5(NAMESPACE_URL, f"{source_id}/{tag.start}/{tag.end}/{tag.tag}/context-v1")


def store_tags(conn, tenant_id, patient_id, source_id, tags):
    """Idempotent: ids are derived from the source span, so a worker retry cannot duplicate."""
    created = 0
    for tag in tags:
        created += conn.execute(
            "INSERT INTO context_tags(tenant_id,patient_id,id,kind,tag,source_id,fact_id,quote,"
            "start_offset,end_offset,valid_from,valid_to,extracted_by) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (tenant_id, patient_id, tag_id(source_id, tag), tag.kind, tag.tag, source_id,
             fact_id(source_id, tag.candidate), tag.quote, tag.start, tag.end, tag.valid_from,
             tag.valid_to, tag.extracted_by),
        ).rowcount
    return created
