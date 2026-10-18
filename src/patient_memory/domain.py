from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_serializer,
    model_validator,
)


def now():
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatientInput(Contract):
    external_id: str = Field(min_length=1, max_length=128)


class Record(Contract):
    concept: str = Field(min_length=1, max_length=128)
    value: str | FiniteFloat | bool
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
    author_role: Literal["nurse", "psw", "patient", "system"]
    author_principal_id: UUID | None = None
    visibility: Literal["care_team", "patient_and_care_team"] = "care_team"
    recorded_at: AwareDatetime
    effective_from: AwareDatetime | None = None
    effective_to: AwareDatetime | None = None
    supersedes_version_id: UUID | None = None
    text: str | None = Field(default=None, min_length=1)
    records: list[Record] | None = Field(default=None, min_length=1, max_length=1000)

    @model_serializer(mode="wrap")
    def legacy_compatible_payload(self, handler):
        payload = handler(self)
        # Source bytes and fixture/reset hashes predate this optional attribution field.
        if self.author_principal_id is None:
            payload.pop("author_principal_id", None)
        return payload

    @model_validator(mode="after")
    def valid_content(self):
        if bool(self.text) == bool(self.records):
            raise ValueError("Supply exactly one of text or records")
        if (self.kind in {"nursing_note", "patient_report"}) != bool(self.text):
            raise ValueError("Source kind does not match content")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("Inverted effective interval")
        expected = {"nursing_note": "nurse", "patient_report": "patient"}.get(self.kind, "system")
        allowed = {"nurse", "psw"} if self.kind == "nursing_note" else {expected}
        if self.author_role not in allowed:
            raise ValueError("Source kind and author role disagree")
        if self.author_principal_id is not None and self.kind != "nursing_note":
            raise ValueError("Explicit authorship is supported only for care notes")
        if self.author_role == "psw" and self.author_principal_id is None:
            raise ValueError("PSW authorship requires an explicit principal")
        if self.kind == "medication_event" and any(not r.event_type for r in self.records or []):
            raise ValueError("Medication events require event_type")
        return self


class ContextInput(Contract):
    kind: Literal["explainer", "amplifier"]
    tag: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=500)
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_window(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("Inverted validity window")
        return self


class ContextTagOut(Contract):
    id: UUID
    kind: Literal["explainer", "amplifier"]
    tag: str
    label: str
    quote: str
    start_offset: int
    end_offset: int
    source_id: UUID
    valid_from: AwareDatetime
    valid_to: AwareDatetime | None
    extracted_by: Literal["structured", "gemini"]


class NoteExtractionResult(Contract):
    processed: int
    tags_created: int
    methods: list[Literal["keyword", "gemini"]]
    batch_limit: int


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
    role: Literal["importer", "nurse", "patient", "psw"]
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


CheckMode = Literal["resident", "runner", "live"]


class CheckQuality(Contract):
    duration_s: float
    speech_s: float
    snr_db: float | None
    clipped: bool
    reasons: list[str]


class CheckFeatures(Contract):
    """None means the feature is undefined for this clip, which is not the same as zero."""

    speech_rate_wpm: float | None
    pause_ratio: float | None
    mean_pause_s: float | None
    f0_median_hz: float | None


class CheckWord(Contract):
    w: str
    start: float
    end: float


class CheckPause(Contract):
    start: float
    end: float


class CheckResult(Contract):
    check_id: UUID
    ts: AwareDatetime
    usable: bool
    quality: CheckQuality
    features: CheckFeatures
    words: list[CheckWord]
    pauses: list[CheckPause]
    # Stay null until the change engine (BL-08) and verdict table (BL-11) exist; unusable
    # clips never get either.
    change: dict | None = None
    assessment: dict | None = None
    timings_ms: dict[str, int]
    session: "SessionSummary | None" = None


class CheckReceipt(Contract):
    """What a PSW gets back from POST /checks: no features, change, verdict or SBAR."""

    check_id: UUID
    ts: AwareDatetime
    usable: bool


class MotionFeatures(Contract):
    sit_to_stand_s: FiniteFloat | None = Field(default=None, gt=0, le=10)
    trunk_sway: FiniteFloat | None = Field(default=None, ge=0, le=5)
    step_cadence_spm: FiniteFloat | None = Field(default=None, gt=0, le=360)


class MotionQuality(Contract):
    duration_s: FiniteFloat = Field(ge=0, le=12)
    total_frames: int = Field(ge=0, le=1000)
    confident_frames: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def frame_counts(self):
        if self.confident_frames > self.total_frames:
            raise ValueError("confident frame count exceeds total frames")
        return self


class MotionInput(Contract):
    device_id: str = Field(min_length=1, max_length=128)
    device_ts: AwareDatetime | None = None
    prompt_version: Literal["pose-chair-steps-v1"] = "pose-chair-steps-v1"
    is_baseline: bool = False
    features: MotionFeatures
    quality: MotionQuality

    @model_validator(mode="after")
    def event_within_capture(self):
        if (self.features.sit_to_stand_s is not None
                and self.features.sit_to_stand_s > self.quality.duration_s):
            raise ValueError("rise time exceeds capture duration")
        return self


class MotionQualityOut(MotionQuality):
    confident_fraction: float = Field(ge=0, le=1)
    reasons: list[str]
    producer: Literal["client-derived"]
    protocol: Literal["pose-chair-steps-v1"]


class MotionResult(Contract):
    check_id: UUID
    ts: AwareDatetime
    usable: bool
    quality: MotionQualityOut
    features: MotionFeatures
    source_id: UUID | None = None
    evidence_ids: list[UUID] = []
    change: dict | None = None
    assessment: dict | None = None


class DocumentedObservation(Contract):
    evidence_id: UUID
    source_id: UUID
    concept: Literal["temperature_c"]
    value: FiniteFloat
    unit: Literal["C"]
    label: str
    quote: str
    recorded_at: AwareDatetime
    effective_at: AwareDatetime
    source_kind: Literal["observation"]


class ResidentOverview(Contract):
    patient_id: UUID
    display_name: str
    synthetic: bool
    watch_window: dict
    features: dict
    series: dict
    baseline: dict
    first_change_ts: AwareDatetime | None
    latest_assessment: dict | None
    context_tags: list[dict]
    documented_observations: list[DocumentedObservation]


ConsentScope = Literal["voice_check", "vox_encounter", "motion_check"]
ConsentState = Literal["granted", "declined", "withdrawn", "expired", "unknown"]


class ConsentInput(Contract):
    """Appends a consent row; the latest row wins and applies to the next check."""

    scope: ConsentScope = "voice_check"
    status: Literal["granted", "declined", "withdrawn"]
    decided_by: Literal["resident", "substitute_decision_maker", "synthetic_fixture"]
    sdm_reference: str | None = Field(None, min_length=1, max_length=200)
    expires_at: AwareDatetime | None = None
    note: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def consistent(self):
        if self.decided_by == "substitute_decision_maker" and not self.sdm_reference:
            raise ValueError("sdm_reference is required for a substitute decision-maker")
        if self.expires_at and (self.status != "granted" or self.expires_at <= now()):
            raise ValueError("expires_at applies to a future expiry of granted consent only")
        return self


class ConsentView(Contract):
    scope: ConsentScope
    state: ConsentState
    decided_by: str | None
    recorded_at: AwareDatetime | None
    expires_at: AwareDatetime | None


class SkipInput(Contract):
    reason: Literal["declined", "asleep", "unwell", "not_available", "other"]
    device_ts: AwareDatetime | None = None


class SkipReceipt(Contract):
    skip_id: UUID
    recorded_at: AwareDatetime


class CheckProfileInput(Contract):
    preferred_locale: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=35)
    first_name: str | None = Field(default=None, min_length=1, max_length=80)

    @model_validator(mode="after")
    def clean_name(self):
        if self.first_name is not None:
            if not self.first_name.strip() or self.first_name != self.first_name.strip():
                raise ValueError("Supply an explicit trimmed first name")
        return self


class CheckProfile(Contract):
    first_name: str | None
    preferred_locale: str | None
    version: UUID | None
    state: Literal["ready", "unconfigured", "unsupported"]
    protocol_locale: Literal["en"] | None
    prompt_version: Literal["count20-days-v1"] | None
    can_configure: bool = False
    can_record_consent: bool = False


class DueResident(Contract):
    """Deliberately score-free: no verdict, fused z, feature, sparkline or SBAR fields."""

    patient_id: UUID
    display_name: str
    status: Literal["due", "done", "skipped", "consent_needed", "language_unavailable"]
    check_profile: CheckProfile
    consent_state: ConsentState
    last_check_ts: AwareDatetime | None
    skipped_today: bool
    # Positive feedback only; missing attribution or a current eligible citation stays unknown.
    observation_helped: Literal[True] | None = None


class DueList(Contract):
    day_start: AwareDatetime
    residents: list[DueResident]


SessionStatus = Literal["arming", "active", "escalating", "acknowledged", "ended"]
SessionContextTag = Literal["exertion", "loud_venue"]


class SessionContactInput(Contract):
    name: str = Field(min_length=1, max_length=40)
    phone_e164: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")


class SessionArm(Contract):
    """Arm a KAZE safety session (decision 018). `ends_at` is checked against the server clock."""

    display_name: str = Field(min_length=1, max_length=40)
    ends_at: AwareDatetime
    interval_min: int = Field(default=45, ge=1, le=180)
    contacts: list[SessionContactInput] = Field(min_length=1, max_length=2)
    context_tags: list[SessionContextTag] = Field(default_factory=list, max_length=2)
    escalation_enabled: bool = True

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.context_tags)) != len(self.context_tags):
            raise ValueError("Duplicate context tag")
        if len({c.phone_e164 for c in self.contacts}) != len(self.contacts):
            raise ValueError("Duplicate contact phone")
        return self


class SessionEnd(Contract):
    pass


class SessionSummary(Contract):
    id: UUID
    status: SessionStatus
    baseline_required: int
    baseline_usable: int
    next_due_at: AwareDatetime | None


class SessionContactOut(Contract):
    contact_index: int
    name: str
    phone_masked: str


class SessionCheckOut(Contract):
    id: UUID
    ts: AwareDatetime
    usable: bool
    is_baseline: bool
    change_status: str | None
    has_location: bool


class EscalationOut(Contract):
    id: UUID
    episode: int
    level: int
    trigger: Literal["missed_checkin", "speech_change"]
    channel: Literal["nudge", "sms"]
    contact_index: int | None
    sent_at: AwareDatetime
    delivery: Literal["pending", "logged", "sent", "failed"]
    message: str | None
    ack_at: AwareDatetime | None


class SessionBaseline(Contract):
    required: int
    usable: int


class SessionOut(Contract):
    id: UUID
    patient_id: UUID
    display_name: str
    status: SessionStatus
    created_at: AwareDatetime
    activated_at: AwareDatetime | None
    ends_at: AwareDatetime
    interval_min: int
    context_tags: list[SessionContextTag]
    escalation_enabled: bool
    next_due_at: AwareDatetime | None
    last_checkin_at: AwareDatetime | None
    ladder_level: int
    episode: int
    ladder_trigger: Literal["missed_checkin", "speech_change"] | None
    acknowledged_at: AwareDatetime | None
    ended_at: AwareDatetime | None
    end_reason: Literal["user", "expired"] | None
    delete_after: AwareDatetime | None
    baseline: SessionBaseline
    contacts: list[SessionContactOut]
    checks: list[SessionCheckOut] = []
    escalations: list[EscalationOut] = []


class SessionList(Contract):
    sessions: list[SessionOut]


CheckResult.model_rebuild()


class VoxSegment(Contract):
    """One diarized turn of a MOCK Vox Advantage encounter (docs/06-baseline.md, BL-32).

    `text` is accepted for shape compatibility and never stored or used: the transcript comes
    from our own ASR on resident audio only, so staff words cannot reach storage.
    """

    speaker: Literal["resident", "staff", "other"]
    start: FiniteFloat = Field(ge=0)
    end: FiniteFloat = Field(ge=0)
    text: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class VoxSegmentCounts(Contract):
    resident: int
    staff: int
    other: int


class VoxEncounterResult(Contract):
    """Result of the MOCK Vox adapter. Not a PointClickCare or Vox Advantage integration."""

    mock: Literal[True] = True
    adapter: Literal["vox-advantage-mock-v1"] = "vox-advantage-mock-v1"
    resident_id: UUID
    prompt_version: Literal["free-conversation-v1"] = "free-conversation-v1"
    usable: bool
    reasons: list[str]
    # Resident-labelled speech left after any overlap with staff or other speakers is cut out.
    resident_speech_s: float
    # Seconds actually analyzed: the resident speech, capped at the adapter's analysis limit.
    analyzed_s: float
    truncated: bool
    segments: VoxSegmentCounts
    check: CheckResult
