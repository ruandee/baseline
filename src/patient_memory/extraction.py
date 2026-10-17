"""Conservative offline extraction. Notes remain attributed source assertions."""
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from patient_memory.domain import SourceInput

STOP_WORDS = {"the", "a", "an", "is", "was", "what", "how", "does", "do", "patient", "reports",
              "has", "have", "about", "of", "and", "in", "on", "to", "since", "documented",
              "current", "currently", "any", "with", "for", "tell", "me", "are", "did", "it",
              "recorded", "been", "record", "records", "notes", "note", "chart", "information",
              "available", "mentioned", "evidence", "known", "find", "can", "you", "list",
              "there", "say", "give", "describe", "supported", "regarding"}


def terms(text):
    return {w for w in re.findall(r"\w+", text.casefold()) if w not in STOP_WORDS}


def embed(text):
    """Hash bag of words: deterministic plumbing baseline, not semantic embeddings."""
    values = [0.0] * 64
    for term in terms(text):
        h = hashlib.sha256(term.encode()).digest()
        values[int.from_bytes(h[:2]) % 64] += 1 if h[2] % 2 else -1
    norm = math.sqrt(sum(v * v for v in values)) or 1
    return [v / norm for v in values]


def vector_sql(vector):
    return "[" + ",".join(str(v) for v in vector) + "]"


@dataclass
class Candidate:
    concept: str
    value: str
    quote: str
    start: int
    end: int
    valid_from: datetime | None
    valid_to: datetime | None
    polarity: str = "uncertain"
    experiencer: str = "unspecified"
    unit: str | None = None
    event_type: str | None = None
    order_id: str | None = None


def extract(source: SourceInput):
    candidates = []
    if source.text is not None:
        canonical = source.text.replace("\r\n", "\n").replace("\r", "\n")
        # Sentence boundaries plus hard 1,600-code-point spans bound the offline context.
        for match in re.finditer(r"[^\n.!?]+[.!?]?", canonical):
            for offset in range(match.start(), match.end(), 1600):
                end = min(offset + 1600, match.end())
                raw = canonical[offset:end]
                start = offset + len(raw) - len(raw.lstrip())
                quote = raw.strip()
                if not quote:
                    continue
                candidates.append(Candidate(
                    concept="source_assertion", value=quote, quote=quote,
                    start=start, end=start + len(quote),
                    valid_from=source.effective_from, valid_to=source.effective_to,
                ))
    else:
        lines = []
        for record in source.records or []:
            quote = f"{record.concept}: {record.value}"
            if record.unit:
                quote += f" {record.unit}"
            quote += f" [polarity={record.polarity}"
            if record.event_type:
                quote += f", event={record.event_type}, order={record.order_id or 'unlinked'}"
            quote += "]"
            start = sum(len(line) + 1 for line in lines)
            lines.append(quote)
            candidates.append(Candidate(
                concept=record.concept, value=str(record.value), unit=record.unit,
                quote=quote, start=start, end=start + len(quote),
                valid_from=record.effective_from or source.effective_from,
                valid_to=record.effective_to or source.effective_to,
                polarity=record.polarity, experiencer="patient",
                event_type=record.event_type, order_id=record.order_id,
            ))
        canonical = "\n".join(lines)
    for c in candidates:
        if canonical[c.start:c.end] != c.quote:
            raise ValueError("invalid_evidence_span")
        if c.valid_from and c.valid_to and c.valid_to < c.valid_from:
            raise ValueError("invalid_effective_interval")
    return canonical, candidates


def fact_id(source_id, candidate):
    return uuid5(NAMESPACE_URL, f"{source_id}/{candidate.start}/{candidate.end}/extract-v1")
