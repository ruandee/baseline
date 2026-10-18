"""BL-33: export a stored, validated SBAR as a preliminary FHIR R4 DocumentReference.

This is a read-only projection. It never calls a model, never rewrites the stored SBAR text and
never sends data anywhere: the "sign-off queue" in the UI is a preview of this payload, not EHR
writeback (decision 020). Availability follows decision 015: an invalidated assessment, a
source-revision mismatch or a citation that no longer resolves returns an explicit unavailable
state instead of an older copy.
"""
import base64
import hashlib
import html
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from patient_memory.baseline.sbar import Sentence
from patient_memory.errors import Problem
from patient_memory.ingestion import lock_patient
from patient_memory.storage import patient_access

NOTE_TYPE_TEXT = "Baseline change-of-condition draft"
EXT = "urn:baseline:fhir:StructureDefinition/"
TAG_SYSTEM = "urn:baseline:tag"
ASSESSMENT_SYSTEM = "urn:baseline:assessment"
# Citation identifiers keep the BL-12 split: fact UUIDs resolve through /evidence/{fact_id};
# check:<uuid> citations are signal data and must never be sent to the fact-only endpoint.
FACT_SYSTEM = "urn:baseline:evidence:fact"
CHECK_SYSTEM = "urn:baseline:evidence:voice-check"
SIGNAL_SYSTEM = "urn:baseline:evidence:signal-capture"
AUTHOR_DISPLAY = {
    "template": "Baseline SBAR drafter (deterministic template)",
    "gemini": "Baseline SBAR drafter (configured model, server-validated assembly)",
}
DESCRIPTION = ("Preliminary draft from a deterministic Baseline assessment. Requires clinician "
               "review and sign-off; not a diagnosis and not a signed note.")


class StoredSbar(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    source: Literal["gemini", "template"]
    sentences: list[Sentence] = Field(min_length=4, max_length=12)


def unavailable(reason: str):
    return Problem(409, "note_unavailable", reason)


def note_text(sbar: StoredSbar) -> str:
    """One line per stored sentence, in stored order; the sentence text is copied verbatim."""
    return "\n".join(f"{s.section}: {s.text}" for s in sbar.sentences)


def citation_reference(evidence_id: str, check_id: str, allowed_checks=None) -> dict:
    if evidence_id.startswith("check:"):
        value = evidence_id.removeprefix("check:")
        if value not in (allowed_checks if allowed_checks is not None else {check_id}):
            raise unavailable("SBAR cites a check other than its assessment's check.")
        return {"type": "Observation", "identifier": {"system": CHECK_SYSTEM, "value": value},
                "display": "Voice check (signal data)"}
    try:
        value = str(UUID(evidence_id))
    except ValueError as exc:
        raise unavailable("SBAR citation is not a recognised evidence identifier.") from exc
    return {"identifier": {"system": FACT_SYSTEM, "value": value},
            "display": "Source evidence fact"}


def build_document_reference(row: dict, sbar: StoredSbar) -> dict:
    """Pure projection of an authorized, current assessment row and its stored SBAR."""
    check_id = str(row["check_id"])
    text = note_text(sbar)
    data = text.encode("utf-8")
    created = row["created_at"].isoformat()
    related, seen, sentences = [], set(), []
    for sentence in sbar.sentences:
        evidence = []
        for evidence_id in sentence.evidence_ids:
            reference = citation_reference(evidence_id, check_id, row.get("allowed_checks"))
            evidence.append({"url": "evidence", "valueReference": reference})
            if evidence_id not in seen:
                seen.add(evidence_id)
                related.append(reference)
        sentences.append({"url": EXT + "sbar-sentence", "extension": [
            {"url": "section", "valueCode": sentence.section},
            {"url": "text", "valueString": sentence.text}, *evidence]})
    lines = "".join(f"<p>{html.escape(line)}</p>" for line in text.split("\n"))
    resource = {
        "resourceType": "DocumentReference",
        "id": str(row["id"]),
        "meta": {"tag": [{"system": TAG_SYSTEM, "code": "synthetic",
                          "display": "Synthetic demo data"},
                         {"system": TAG_SYSTEM, "code": "draft-preview",
                          "display": "Preview only; not sent to any clinical system"}]},
        "text": {"status": "generated",
                 "div": f'<div xmlns="http://www.w3.org/1999/xhtml">{lines}</div>'},
        "extension": [
            {"url": EXT + "sbar-source", "valueCode": sbar.source},
            {"url": EXT + "assessment-provenance", "extension": [
                {"url": "assessment", "valueIdentifier": {"system": ASSESSMENT_SYSTEM,
                                                          "value": str(row["id"])}},
                {"url": "check", "valueIdentifier": {"system": (CHECK_SYSTEM if row["params"].get("modality", "speech") == "speech" else SIGNAL_SYSTEM), "value": check_id}},
                {"url": "sourceRevision", "valueInteger": int(row["params"]["source_revision"])},
                {"url": "changeStatus", "valueCode": row["change_status"]},
                {"url": "verdict", "valueCode": row["verdict"]},
                {"url": "suggestedAction", "valueCode": row["suggested_action"]},
            ]},
            *sentences,
        ],
        "identifier": [{"system": ASSESSMENT_SYSTEM, "value": str(row["id"])}],
        "status": "current",
        "docStatus": "preliminary",
        "type": {"text": NOTE_TYPE_TEXT},
        "category": [{"text": "Draft note awaiting clinician sign-off"}],
        "subject": {"reference": f"Patient/{row['patient_id']}", "type": "Patient",
                    "display": row["external_id"]},
        "date": created,
        "author": [{"type": "Device", "display": AUTHOR_DISPLAY[sbar.source]}],
        "description": DESCRIPTION,
        "content": [{"attachment": {
            "contentType": "text/plain; charset=utf-8", "language": "en",
            "data": base64.b64encode(data).decode("ascii"), "size": len(data),
            "hash": base64.b64encode(hashlib.sha1(data).digest()).decode("ascii"),
            "title": "SBAR draft (preliminary)", "creation": created}}],
        "context": {"period": {"start": row["check_ts"].isoformat(),
                               "end": row["check_ts"].isoformat()},
                    "related": related},
    }
    problems = validate_document_reference(resource) + validate_baseline_profile(resource, text)
    if problems:  # fail closed: never hand out a payload that does not meet the shape
        raise Problem(500, "internal_error")
    return resource


def draft_note(conn, patient_id: UUID, assessment_id: UUID) -> dict:
    """Authorize before retrieval; return 404 on denial and 409 when no current draft exists."""
    lock_patient(conn, patient_id)  # same lock as source mutation, so the read is consistent
    patient_access(conn, patient_id)
    if not conn.execute("SELECT pm_care(%s) AS ok", (patient_id,)).fetchone()["ok"]:
        raise Problem(404, "not_found")
    row = conn.execute(
        "SELECT a.*, p.external_id, p.revision, COALESCE((a.params->>'signal_ts')::timestamptz,v.ts) AS check_ts, v.usable FROM assessments a "
        "JOIN patients p ON p.tenant_id=a.tenant_id AND p.id=a.patient_id "
        "LEFT JOIN voice_checks v ON v.tenant_id=a.tenant_id AND v.patient_id=a.patient_id "
        "AND v.id=a.check_id WHERE a.patient_id=%s AND a.id=%s",
        (patient_id, assessment_id)).fetchone()
    if not row:
        raise Problem(404, "not_found")
    params = row["params"] or {}
    if params.get("invalidated") or params.get("source_revision") != row["revision"]:
        raise unavailable("The SBAR draft was invalidated by a source change. "
                          "A new usable check is needed before a draft note can be exported.")
    if (params.get("modality", "speech") == "speech" and not row["usable"]) or row["verdict"] not in ("escalate", "watch") or not row["sbar"]:
        raise unavailable("This assessment has no SBAR draft to export.")
    try:
        sbar = StoredSbar.model_validate(row["sbar"])
    except ValidationError as exc:
        raise unavailable("The stored SBAR draft is not in the expected shape.") from exc
    row["allowed_checks"] = validate_signal_citations(conn, patient_id, row, sbar)
    facts = {e for s in sbar.sentences for e in s.evidence_ids if not e.startswith("check:")}
    if facts:
        try:
            wanted = [UUID(f) for f in facts]
        except ValueError as exc:
            raise unavailable("SBAR citation is not a recognised evidence identifier.") from exc
        # Same visibility as GET /evidence/{fact_id}: RLS plus published, non-retracted source.
        found = {str(r["id"]) for r in conn.execute(
            "SELECT f.id FROM facts f JOIN sources s ON s.tenant_id=f.tenant_id "
            "AND s.patient_id=f.patient_id AND s.id=f.source_id WHERE f.patient_id=%s "
            "AND f.id=ANY(%s) AND s.published_at IS NOT NULL AND s.retracted_at IS NULL "
            "AND s.purged_at IS NULL AND (f.valid_to IS NULL OR f.valid_to>clock_timestamp()) AND NOT EXISTS(SELECT FROM sources newer "
            "WHERE newer.tenant_id=s.tenant_id AND newer.patient_id=s.patient_id "
            "AND newer.supersedes=s.id AND newer.published_at IS NOT NULL "
            "AND newer.retracted_at IS NULL AND newer.purged_at IS NULL)", (patient_id, wanted))}
        if found != {str(w) for w in wanted}:
            raise unavailable("A cited source is no longer available to this account.")
    return build_document_reference(row, sbar)


def validate_signal_citations(conn, patient_id, row, sbar, now=None):
    """Resolve typed capture citations under RLS; never trust a UUID merely for membership.

    Multimodal drafts remain tied to current registered snapshots and expire with their
    contributing captures. Historical voice baselines retain their actual times and prompt.
    """
    now = now or datetime.now(UTC)
    params = row["params"]
    wanted = {e.removeprefix("check:") for s in sbar.sentences for e in s.evidence_ids
              if e.startswith("check:")}
    if params.get("draft_status") != "multimodal_template":
        if wanted - {str(row["check_id"])}:
            raise unavailable("SBAR cites an unrelated voice check.")
        return wanted
    context_ids = params.get("draft_context_ids", [])
    if context_ids:
        rows = conn.execute("SELECT id FROM context_tags WHERE patient_id=%s AND id=ANY(%s::uuid[]) "
                            "AND valid_from<=%s AND (valid_to IS NULL OR valid_to>%s)",
                            (patient_id, context_ids, now, now)).fetchall()
        if {str(r["id"]) for r in rows} != set(context_ids):
            raise unavailable("Cited context has expired or is unavailable.")
    modalities = params.get("modality_results", {})
    speech = modalities.get("speech", {})
    allowed = {e.removeprefix("check:") for e in [*speech.get("evidence_ids", []),
                *speech.get("params", {}).get("baseline_evidence_ids", [])] if e.startswith("check:")}
    if wanted - allowed:
        raise unavailable("SBAR cites an unrelated voice capture.")
    from patient_memory.baseline.engine import REGISTRY
    for name, entry in modalities.items():
        if not entry.get("current") or entry.get("status") not in ("provisional", "change"):
            continue
        try:
            event = datetime.fromisoformat(entry["ts"])
        except (KeyError, TypeError, ValueError) as exc:
            raise unavailable("Signal event time is unavailable.") from exc
        if name not in REGISTRY or event > now or now-event > timedelta(hours=24):
            raise unavailable("A contributing signal has expired.")
    if wanted:
        try:
            ids = [UUID(e) for e in wanted]
        except ValueError as exc:
            raise unavailable("Invalid voice capture citation.") from exc
        rows = conn.execute("SELECT id,prompt_version,ts FROM voice_checks WHERE patient_id=%s "
                            "AND id=ANY(%s) AND usable AND session_id IS NULL", (patient_id, ids)).fetchall()
        if {str(r["id"]) for r in rows} != wanted or len({r["prompt_version"] for r in rows}) != 1:
            raise unavailable("A cited voice capture is unavailable or uses a different prompt.")
        if any(r["ts"] > now for r in rows):
            raise unavailable("A cited voice capture is in the future.")
    return wanted


# --- FHIR R4 DocumentReference shape validator (no external dependency) -----------------------

ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
CODE = re.compile(r"^[^\s]+( [^\s]+)*$")
INSTANT = re.compile(
    r"^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:"
    r"([0-5][0-9]|60)(\.[0-9]+)?(Z|[+-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00))$")
DATETIME = re.compile(
    r"^([0-9]{4})(-(0[1-9]|1[0-2])(-(0[1-9]|[12][0-9]|3[01])(T([01][0-9]|2[0-3]):[0-5][0-9]:"
    r"([0-5][0-9]|60)(\.[0-9]+)?(Z|[+-]((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?$")
BASE64 = re.compile(r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$")
STATUS = {"current", "superseded", "entered-in-error"}
DOC_STATUS = {"preliminary", "final", "amended", "entered-in-error"}
NARRATIVE_STATUS = {"generated", "extensions", "additional", "empty"}
TOP = {"resourceType", "id", "meta", "implicitRules", "language", "text", "contained",
       "extension", "modifierExtension", "masterIdentifier", "identifier", "status", "docStatus",
       "type", "category", "subject", "date", "author", "authenticator", "custodian",
       "relatesTo", "description", "securityLabel", "content", "context"}
CODING = {"id", "extension", "system", "version", "code", "display", "userSelected"}
CONCEPT = {"id", "extension", "coding", "text"}
REFERENCE = {"id", "extension", "reference", "type", "identifier", "display"}
IDENTIFIER = {"id", "extension", "use", "type", "system", "value", "period", "assigner"}
ATTACHMENT = {"id", "extension", "contentType", "language", "data", "url", "size", "hash",
              "title", "creation"}
CONTENT = {"id", "extension", "modifierExtension", "attachment", "format"}
CONTEXT = {"id", "extension", "modifierExtension", "encounter", "event", "period",
           "facilityType", "practiceSetting", "sourcePatientInfo", "related"}
PERIOD = {"id", "extension", "start", "end"}
META = {"id", "extension", "versionId", "lastUpdated", "source", "profile", "security", "tag"}
VALUE_TYPES = {"valueString": str, "valueCode": str, "valueInteger": int, "valueBoolean": bool,
               "valueUri": str, "valueReference": dict, "valueIdentifier": dict,
               "valueDateTime": str, "valueCoding": dict}


def _no_empty(value, path, errors):
    """JSON FHIR forbids null, empty strings, empty arrays and empty objects (ele-1)."""
    if value is None or value == "" or value == [] or value == {}:
        errors.append(f"{path}: empty or null value")
    elif isinstance(value, dict):
        for key, item in value.items():
            _no_empty(item, f"{path}.{key}", errors)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _no_empty(item, f"{path}[{i}]", errors)


def _keys(value, allowed, path, errors) -> bool:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected an object")
        return False
    errors.extend(f"{path}.{key}: unknown element" for key in sorted(set(value) - allowed))
    return True


def _list(value, path, errors) -> list:
    if not isinstance(value, list):
        errors.append(f"{path}: expected an array")
        return []
    return value


def _string(value, path, errors):
    if not isinstance(value, str):
        errors.append(f"{path}: expected a string")


def _coding(value, path, errors):
    if _keys(value, CODING, path, errors):
        for key in ("system", "code", "display", "version"):
            if key in value:
                _string(value[key], f"{path}.{key}", errors)


def _concept(value, path, errors):
    if _keys(value, CONCEPT, path, errors):
        for i, coding in enumerate(_list(value.get("coding", []), f"{path}.coding", errors)):
            _coding(coding, f"{path}.coding[{i}]", errors)
        if "text" in value:
            _string(value["text"], f"{path}.text", errors)


def _identifier(value, path, errors):
    if _keys(value, IDENTIFIER, path, errors):
        for key in ("system", "value"):
            if key in value:
                _string(value[key], f"{path}.{key}", errors)
        if "use" in value and value["use"] not in {"usual", "official", "temp", "secondary",
                                                   "old"}:
            errors.append(f"{path}.use: not in IdentifierUse")


def _reference(value, path, errors):
    if _keys(value, REFERENCE, path, errors):
        for key in ("reference", "type", "display"):
            if key in value:
                _string(value[key], f"{path}.{key}", errors)
        if "identifier" in value:
            _identifier(value["identifier"], f"{path}.identifier", errors)
        if not {"reference", "identifier", "display"} & set(value):
            errors.append(f"{path}: reference needs reference, identifier or display")


def _period(value, path, errors):
    if _keys(value, PERIOD, path, errors):
        for key in ("start", "end"):
            if key in value and not (isinstance(value[key], str) and DATETIME.match(value[key])):
                errors.append(f"{path}.{key}: not a FHIR dateTime")


def _extensions(value, path, errors):
    for i, ext in enumerate(_list(value, path, errors)):
        where = f"{path}[{i}]"
        if not isinstance(ext, dict) or not isinstance(ext.get("url"), str):
            errors.append(f"{where}: extension needs a url")
            continue
        values = [k for k in ext if k.startswith("value")]
        unknown = set(ext) - {"id", "url", "extension", *values}
        errors.extend(f"{where}.{key}: unknown element" for key in sorted(unknown))
        nested = "extension" in ext
        if nested == bool(values) or len(values) > 1:  # ext-1: extension or one value[x]
            errors.append(f"{where}: needs exactly one of nested extension or one value[x]")
        for key in values:
            kind = VALUE_TYPES.get(key)
            if kind is None:
                errors.append(f"{where}.{key}: unsupported value[x] type")
            elif not isinstance(ext[key], kind) or (kind is int and isinstance(ext[key], bool)):
                errors.append(f"{where}.{key}: wrong type")
            elif key == "valueReference":
                _reference(ext[key], f"{where}.{key}", errors)
            elif key == "valueIdentifier":
                _identifier(ext[key], f"{where}.{key}", errors)
            elif key == "valueCode" and not CODE.match(ext[key]):
                errors.append(f"{where}.{key}: not a FHIR code")
        if nested:
            _extensions(ext["extension"], f"{where}.extension", errors)


def validate_document_reference(resource) -> list[str]:
    """Check FHIR R4 DocumentReference structure, cardinality and required value sets.

    Covers the elements this export uses plus the base-resource rules; it is a shape check, not
    a full FHIR validator (no terminology server, no profile resolution).
    """
    errors: list[str] = []
    if not isinstance(resource, dict):
        return ["resource: expected an object"]
    _no_empty(resource, "DocumentReference", errors)
    _keys(resource, TOP, "DocumentReference", errors)
    if resource.get("resourceType") != "DocumentReference":
        errors.append("resourceType: must be DocumentReference")
    if "id" in resource and not (isinstance(resource["id"], str) and ID.match(resource["id"])):
        errors.append("id: not a FHIR id")
    if "meta" in resource and _keys(resource["meta"], META, "meta", errors):
        for i, tag in enumerate(_list(resource["meta"].get("tag", []), "meta.tag", errors)):
            _coding(tag, f"meta.tag[{i}]", errors)
    if "text" in resource and _keys(resource["text"], {"id", "extension", "status", "div"},
                                    "text", errors):
        if resource["text"].get("status") not in NARRATIVE_STATUS:
            errors.append("text.status: not in NarrativeStatus")
        div = resource["text"].get("div")
        if not (isinstance(div, str) and div.startswith('<div xmlns="http://www.w3.org/1999/xhtml"')
                and div.endswith("</div>")):
            errors.append("text.div: must be an XHTML div")
    for key in ("extension", "modifierExtension"):
        if key in resource:
            _extensions(resource[key], key, errors)
    for i, identifier in enumerate(_list(resource.get("identifier", []), "identifier", errors)):
        _identifier(identifier, f"identifier[{i}]", errors)
    if "masterIdentifier" in resource:
        _identifier(resource["masterIdentifier"], "masterIdentifier", errors)
    if resource.get("status") not in STATUS:  # 1..1, required binding
        errors.append("status: required, one of " + ", ".join(sorted(STATUS)))
    if "docStatus" in resource and resource["docStatus"] not in DOC_STATUS:
        errors.append("docStatus: not in CompositionStatus")
    if "type" in resource:
        _concept(resource["type"], "type", errors)
    for i, category in enumerate(_list(resource.get("category", []), "category", errors)):
        _concept(category, f"category[{i}]", errors)
    if "subject" in resource:
        _reference(resource["subject"], "subject", errors)
    if "date" in resource and not (isinstance(resource["date"], str)
                                   and INSTANT.match(resource["date"])):
        errors.append("date: not a FHIR instant")
    for key in ("author", "authenticator", "custodian"):
        refs = resource.get(key, [] if key == "author" else {})
        if key == "author":
            for i, ref in enumerate(_list(refs, "author", errors)):
                _reference(ref, f"author[{i}]", errors)
        elif key in resource:
            _reference(refs, key, errors)
    if "description" in resource:
        _string(resource["description"], "description", errors)
    content = resource.get("content")
    if not isinstance(content, list) or not content:  # 1..*
        errors.append("content: required, at least one entry")
        content = []
    for i, item in enumerate(content):
        where = f"content[{i}]"
        if not _keys(item, CONTENT, where, errors):
            continue
        attachment = item.get("attachment")
        if attachment is None:  # 1..1
            errors.append(f"{where}.attachment: required")
        elif _keys(attachment, ATTACHMENT, f"{where}.attachment", errors):
            at = f"{where}.attachment"
            for key in ("contentType", "language"):
                if key in attachment and not (isinstance(attachment[key], str)
                                              and CODE.match(attachment[key])):
                    errors.append(f"{at}.{key}: not a FHIR code")
            if "data" in attachment:
                data = attachment["data"]
                if not (isinstance(data, str) and BASE64.match(data)):
                    errors.append(f"{at}.data: not base64Binary")
                if "contentType" not in attachment:  # att-1
                    errors.append(f"{at}.contentType: required when data is present")
            if "size" in attachment and not (type(attachment["size"]) is int
                                             and attachment["size"] >= 0):
                errors.append(f"{at}.size: not an unsignedInt")
            if "hash" in attachment and not (isinstance(attachment["hash"], str)
                                             and BASE64.match(attachment["hash"])):
                errors.append(f"{at}.hash: not base64Binary")
            if "creation" in attachment and not (isinstance(attachment["creation"], str)
                                                 and DATETIME.match(attachment["creation"])):
                errors.append(f"{at}.creation: not a FHIR dateTime")
            if "title" in attachment:
                _string(attachment["title"], f"{at}.title", errors)
        if "format" in item:
            _coding(item["format"], f"{where}.format", errors)
    if "context" in resource and _keys(resource["context"], CONTEXT, "context", errors):
        context = resource["context"]
        if "period" in context:
            _period(context["period"], "context.period", errors)
        for i, ref in enumerate(_list(context.get("related", []), "context.related", errors)):
            _reference(ref, f"context.related[{i}]", errors)
    return errors


def validate_baseline_profile(resource: dict, expected_text: str | None = None) -> list[str]:
    """BL-33 profile on top of R4: an unsigned preliminary draft carrying the exact SBAR."""
    errors = []
    if resource.get("status") != "current":
        errors.append("status: must be current")
    if resource.get("docStatus") != "preliminary":
        errors.append("docStatus: must be preliminary")
    if "authenticator" in resource:
        errors.append("authenticator: a draft has not been signed")
    if resource.get("type", {}).get("text") != NOTE_TYPE_TEXT:
        errors.append("type.text: must be " + NOTE_TYPE_TEXT)
    if not str(resource.get("subject", {}).get("reference", "")).startswith("Patient/"):
        errors.append("subject: must reference the Patient")
    if not resource.get("author"):
        errors.append("author: provenance of the draft is required")
    try:
        attachment = resource["content"][0]["attachment"]
        data = base64.b64decode(attachment["data"], validate=True)
        text = data.decode("utf-8")
    except (KeyError, IndexError, TypeError, ValueError):
        return errors + ["content[0].attachment.data: missing or not UTF-8 text"]
    if attachment.get("size") != len(data):
        errors.append("content[0].attachment.size: does not match data")
    if attachment.get("hash") != base64.b64encode(hashlib.sha1(data).digest()).decode("ascii"):
        errors.append("content[0].attachment.hash: does not match data")
    if expected_text is not None and text != expected_text:
        errors.append("content[0].attachment.data: does not carry the exact SBAR text")
    return errors
