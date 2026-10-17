from dataclasses import dataclass

from patient_memory.speech.asr import Word
from patient_memory.speech.vad import Span


@dataclass(frozen=True)
class TimingFeatures:
    """None means the feature is undefined for this clip, which is not the same as zero."""

    speech_rate_wpm: float | None
    pause_ratio: float | None
    mean_pause_s: float | None


def timing_features(words: list[Word], pauses: list[Span], span: Span | None) -> TimingFeatures:
    spoken = words[-1].end - words[0].start if len(words) >= 2 else 0
    length = span.end - span.start if span else 0
    paused = sum(p.end - p.start for p in pauses)
    return TimingFeatures(
        speech_rate_wpm=len(words) / spoken * 60 if spoken > 0 else None,
        pause_ratio=paused / length if length > 0 else None,
        mean_pause_s=(paused / len(pauses) if pauses else 0.0) if length > 0 else None,
    )
