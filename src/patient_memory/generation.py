from itertools import combinations
from uuid import uuid4

from patient_memory.domain import Answer, Claim, Conflict, Coverage, Unknown
from patient_memory.errors import Problem
from patient_memory.retrieval import evidence


class ExtractiveGenerator:
    model_id = "extractive-stub-v1"

    def version(self):
        return self.model_id

    def generate(self, question, facts, as_of, shift_start=None):
        claims = []
        for f in facts:
            historical = f["valid_to"] is not None and f["valid_to"] < as_of
            if f["event_type"] == "ordered" and f["order_id"]:
                historical |= any(
                    other["order_id"] == f["order_id"] and other["event_type"] == "stopped"
                    and other["valid_from"] is not None and other["valid_from"] <= as_of
                    for other in facts
                )
            status = "historical" if historical else "documented"
            if f["payload"]["kind"] == "patient_report":
                status = "patient_reported" if not historical else "historical"
            elif f["concept"] == "source_assertion" or f["polarity"] == "uncertain" or f["valid_from"] is None:
                status = "uncertain" if not historical else "historical"
            section = "active_documented_concerns"
            if f["event_type"]:
                section = "documented_medication_events"
            elif f["payload"]["kind"] == "patient_report":
                section = "patient_reported_concerns"
            elif shift_start and f["valid_from"] and f["valid_from"] >= shift_start:
                section = "recent_changes"
            # Quote source text rather than inventing a paraphrase from an offline rule system.
            claims.append(Claim(claim_id=str(f["id"]), section=section, text=f["quote"],
                                epistemic_status=status, evidence_ids=[f["id"]],
                                effective_at=f["valid_from"]))
        return claims


def conflicts_for(facts):
    conflicts = []
    for a, b in combinations(facts, 2):
        if a["concept"] == "source_assertion" or a["concept"] != b["concept"]:
            continue
        if a["order_id"] or b["order_id"] or a["source_id"] == b["source_id"]:
            continue
        if a["valid_to"] and b["valid_from"] and a["valid_to"] < b["valid_from"]:
            continue
        if b["valid_to"] and a["valid_from"] and b["valid_to"] < a["valid_from"]:
            continue
        if a["value"] != b["value"] or a["polarity"] != b["polarity"]:
            conflicts.append(Conflict(topic=a["concept"], claim_ids=[str(a["id"]), str(b["id"])],
                                      evidence_ids=[a["id"], b["id"]]))
    return conflicts


def validate_claims(claims, facts):
    allowed = {f["id"]: f for f in facts}
    for claim in claims:
        if not claim.evidence_ids or any(eid not in allowed for eid in claim.evidence_ids):
            raise ValueError("fabricated_evidence")
        for eid in claim.evidence_ids:
            f = allowed[eid]
            if f["canonical_text"][f["start_offset"]:f["end_offset"]] != f["quote"]:
                raise ValueError("invalid_quote")
        # Prototype guarantees verbatim support; semantic paraphrase needs independent evaluation.
        if claim.text not in [allowed[e]["quote"] for e in claim.evidence_ids]:
            raise ValueError("unsupported_paraphrase")
    return claims


def build_answer(generator, question, facts, coverage, patient_id, revision, as_of, known_at,
                 request_id=None, shift_start=None):
    for attempt in range(2):
        try:
            claims = generator.generate(question, facts, as_of, shift_start)
            claims = validate_claims(claims, facts)
            break
        except (ValueError, TypeError) as exc:
            if attempt:
                raise Problem(502, "invalid_model_output") from exc
    conflicts = conflicts_for(facts)
    unknowns = []
    if not claims:
        unknowns.append(Unknown(topic=question, reason="selection_abstained" if facts else "not_documented"))
    if any(f["valid_from"] is None for f in facts):
        unknowns.append(Unknown(topic="evidence_effective_time", reason="unknown_time"))
    if not coverage["index_complete"]:
        unknowns.append(Unknown(topic="source_processing", reason="not_yet_indexed"))
    if coverage["truncated"]:
        unknowns.append(Unknown(topic="retrieval_coverage", reason="outside_retrieval_window"))
    status = "answered" if claims else "insufficient_evidence"
    if claims and (not coverage["index_complete"] or coverage["truncated"]):
        status = "partial"
    if conflicts:
        status = "conflicting_evidence"
    return Answer(
        request_id=request_id or uuid4(), patient_id=patient_id, status=status, as_of=as_of,
        known_at=known_at, memory_revision=revision, claims=claims,
        evidence=[evidence(f) for f in facts], unknowns=unknowns, conflicts=conflicts,
        coverage=Coverage(**coverage),
        versions={"model": generator.model_id, "prompt": "verbatim-v1", "retriever": "rrf-hash-v1",
                  "extractor": "attributed-span-v1", "embedding": "hash64-v1"},
    )
