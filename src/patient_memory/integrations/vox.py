"""MOCK Vox Advantage encounter adapter (BL-32, decision 016).

Vox Advantage has no public API we could find, so this is a contract we defined ourselves. It is
not a PointClickCare or Vox integration and must be labelled as a mock wherever it is shown.

An encounter is a recorded care conversation plus diarized segments. Only resident speech is
analyzed: resident segments are cut out of the decoded audio, any overlap with a staff or other
segment is removed, and the remaining samples are concatenated and run through the normal
pipeline as `free-conversation-v1`, so they are never compared with the counting prompt.
Segment `text` is never used or stored.
"""
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from pydantic import AwareDatetime, TypeAdapter, ValidationError

from patient_memory.domain import VoxSegment
from patient_memory.errors import Problem
from patient_memory.speech import asr, vad
from patient_memory.speech.pipeline import Analysis, Timer, analyze_pcm, decode_upload
from patient_memory.speech.vad import SAMPLE_RATE

DEVICE_ID = "vox-mock"
# docs/06-baseline.md: at least 8 s of resident speech, else too_little_resident_speech.
MIN_RESIDENT_S = 8.0
# A care conversation runs longer than the 15 s prompt, but bounded: ffmpeg stops decoding just
# past this, and longer encounters are refused rather than silently cut.
MAX_ENCOUNTER_S = 120
# Whisper time grows with audio length; resident speech past this is not analyzed.
MAX_RESIDENT_S = 60.0
MAX_SEGMENTS = 400
# Slivers left between overlapping turns are crosstalk, not usable resident speech.
MIN_FRAGMENT_S = 0.05
# Clock skew allowance for encounter_ts; anything later is a future-dated encounter.
FUTURE_SKEW = timedelta(minutes=5)

_SEGMENTS = TypeAdapter(list[VoxSegment])
_TIMESTAMP = TypeAdapter(AwareDatetime)

Span = tuple[float, float]


def consent_given(parts: list[str] | None) -> bool:
    """Exactly one `consent` part whose raw value is `true`; anything else is a refusal.

    No trimming or case folding, and a repeated part is refused even if one copy says `true`,
    so an ambiguous request never counts as consent.
    """
    return parts == ["true"]


def parse_segments(raw: str | None) -> list[VoxSegment]:
    if not raw:
        raise Problem(422, "invalid_request")
    try:
        segments = _SEGMENTS.validate_python(json.loads(raw))
    except (ValueError, ValidationError) as exc:  # never echo the rejected segment text
        raise Problem(422, "invalid_request") from exc
    if not segments or len(segments) > MAX_SEGMENTS:
        raise Problem(422, "invalid_request")
    return segments


def parse_encounter_ts(raw: str | None, now: datetime | None = None) -> datetime:
    try:
        ts = _TIMESTAMP.validate_python(raw)
    except ValidationError as exc:
        raise Problem(422, "invalid_request") from exc
    if ts > (now or datetime.now(UTC)) + FUTURE_SKEW:
        raise Problem(422, "invalid_request")
    return ts


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def resident_spans(segments: list[VoxSegment], duration_s: float) -> list[Span]:
    """Resident time inside the audio, with every staff/other overlap removed, in order."""
    def clipped(speakers):
        return _merge([(max(0.0, s.start), min(s.end, duration_s)) for s in segments
                       if s.speaker in speakers and min(s.end, duration_s) > max(0.0, s.start)])

    others = clipped({"staff", "other"})
    kept: list[Span] = []
    for start, end in clipped({"resident"}):
        cursor = start
        for o_start, o_end in others:
            if o_end <= cursor or o_start >= end:
                continue
            if o_start > cursor:
                kept.append((cursor, o_start))
            cursor = max(cursor, o_end)
        if cursor < end:
            kept.append((cursor, end))
    return [(s, e) for s, e in kept if e - s >= MIN_FRAGMENT_S]


def extract(audio: np.ndarray, spans: list[Span],
            limit_s: float = MAX_RESIDENT_S) -> tuple[np.ndarray, bool]:
    """Concatenate the spans' samples, keeping at most `limit_s`; returns (audio, truncated)."""
    pieces = [audio[round(s * SAMPLE_RATE):round(e * SAMPLE_RATE)] for s, e in spans]
    joined = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)
    budget = round(limit_s * SAMPLE_RATE)
    return joined[:budget].astype(np.float32, copy=False), len(joined) > budget


@dataclass(frozen=True)
class EncounterAnalysis:
    analysis: Analysis
    resident_speech_s: float
    analyzed_s: float
    truncated: bool
    counts: dict[str, int]


def analyze_encounter(upload: Path, work: Path, segments: list[VoxSegment],
                      transcribe: Callable[[np.ndarray], list[asr.Word]]) -> EncounterAnalysis:
    """Decode the whole encounter (bounded), keep resident speech only and analyze it.

    Under MIN_RESIDENT_S of resident speech nothing is transcribed: the result is an unusable
    analysis with reason `too_little_resident_speech`, stored like any unusable check.
    """
    timer = Timer()
    audio = decode_upload(upload, work, timer, MAX_ENCOUNTER_S)
    spans = resident_spans(segments, len(audio) / SAMPLE_RATE)
    resident, truncated = timer("extract", extract, audio, spans)
    # Diarized turn duration includes pauses; require actual voiced samples before ASR.
    runs = timer("resident_vad", lambda: vad.voiced_runs(vad.frame_flags(resident)))
    resident_s = sum(r.end - r.start for r in runs)
    speakers = Counter(s.speaker for s in segments)
    counts = {k: speakers.get(k, 0) for k in ("resident", "staff", "other")}
    if resident_s < MIN_RESIDENT_S:
        analysis = Analysis(
            usable=False,
            quality={"duration_s": round(len(resident) / SAMPLE_RATE, 2),
                     "speech_s": round(resident_s, 2),
                     "snr_db": None, "clipped": False,
                     "reasons": ["too_little_resident_speech"]},
            features={"speech_rate_wpm": None, "pause_ratio": None, "mean_pause_s": None,
                      "f0_median_hz": None},
            words=[], pauses=[], timings_ms=timer.timings)
        return EncounterAnalysis(analysis, resident_s, len(resident) / SAMPLE_RATE, truncated, counts)
    analysis = analyze_pcm(resident, transcribe, timer, on_script=False)
    return EncounterAnalysis(analysis, resident_s, len(resident) / SAMPLE_RATE, truncated, counts)
