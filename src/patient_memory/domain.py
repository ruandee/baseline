from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


def now():
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientInput(Contract):
    external_id: str = Field(min_length=1, max_length=128)


class Record(Contract):
    concept: str = Field(min_length=1, max_length=128)
    value: str | float | bool
    unit: str | None = None
    polarity: Literal["present", "absent", "uncertain"] = "present"
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None
    order_id: str | None = None
    event_type: Literal["ordered", "administered", "stopped", "mentioned"] | None = None

    @model_validator(mode="after")
    def validate_interval(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Inverted effective interval")
        if self.event_type in {"ordered", "stopped"} and not self.order_id:
            raise ValueError("Order identity is required")
        return self


class SourceInput(Contract):
    external_document_id: str = Field(min_length=1, max_length=128)
    external_version_id: str = Field(min_length=1, max_length=128)
    source_system: str = Field(min_length=1, max_length=128)
    kind: Literal["nursing_note", "patient_report", "observation", "medication_event"]
    author_role: Literal["nurse", "patient", "system"]
    visibility: Literal["care_team", "patient_and_care_team"] = "care_team"
    recorded_at: AwareDatetime
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None
    supersedes_version_id: UUID | None = None
    text: str | None = Field(default=None, min_length=1)
    records: list[Record] | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_content(self):
        if bool(self.text) == bool(self.records):
            raise ValueError("Supply exactly one of text or records")
        if (self.kind in {"nursing_note", "patient_report"}) != bool(self.text):
            raise ValueError("Source kind does not match content")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Inverted effective interval")
        expected = {"nursing_note": "nurse", "patient_report": "patient"}.get(self.kind, "system")
        if self.author_role != expected:
            raise ValueError("Source kind and author role disagree")
        if self.kind == "medication_event" and any(not r.event_type for r in self.records or []):
            raise ValueError("Medication events require event_type")
        return self


class Question(Contract):
    question: str = Field(min_length=1, max_length=4000)
    as_of: AwareDatetime | None = None
    known_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_cutoff(self):
        if self.known_at and self.known_at > now():
            raise ValueError("known_at cannot be in the future")
        return self


class Summary(Contract):
    shift_start: AwareDatetime
    shift_end: AwareDatetime
    known_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def valid_cutoffs(self):
        if self.shift_end < self.shift_start:
            raise ValueError("Inverted shift interval")
        if self.known_at and self.known_at > now():
            raise ValueError("known_at cannot be in the future")
        return self


class Reason(Contract):
    reason: str = Field(min_length=1, max_length=1000)


class AssignmentInput(Contract):
    principal_id: UUID
    role: Literal["importer", "nurse", "patient"]
    active: bool = True


class VisibilityInput(Contract):
    visibility: Literal["care_team", "patient_and_care_team"]


class Claim(Contract):
    claim_id: str
    section: str
    text: str
    epistemic_status: Literal["documented", "patient_reported", "historical", "uncertain"]
    evidence_ids: list[UUID] = Field(min_length=1)
    effective_at: AwareDatetime | None


class Evidence(Contract):
    evidence_id: UUID
    source_version_id: UUID
    source_kind: str
    author_role: str
    recorded_at: AwareDatetime
    ingested_at: AwareDatetime
    quote: str
    start: int = Field(ge=0)
    end: int = Field(ge=1)


class Coverage(Contract):
    index_complete: bool
    truncated: bool
    degraded_mode: str | None = None


class Unknown(Contract):
    topic: str
    reason: str


class Conflict(Contract):
    topic: str
    claim_ids: list[str]
    evidence_ids: list[UUID]
    resolution: None = None


class Answer(Contract):
    request_id: UUID
    patient_id: UUID
    status: Literal["answered", "partial", "insufficient_evidence", "conflicting_evidence"]
    as_of: AwareDatetime
    known_at: AwareDatetime
    memory_revision: int
    claims: list[Claim]
    evidence: list[Evidence]
    unknowns: list[Unknown]
    conflicts: list[Conflict]
    coverage: Coverage
    versions: dict[str, str]
