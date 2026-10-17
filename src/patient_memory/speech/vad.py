from dataclasses import dataclass

import numpy as np
import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_S = FRAME_MS / 1000
AGGRESSIVENESS = 2
# webrtcvad keeps flagging voice about 120 ms after speech stops; without trimming it every
# pause measures 120 ms short and 250-370 ms pauses vanish (see docs/06-baseline.md).
HANGOVER_FRAMES = 4
# The startup burst seen with any noise floor is 90 ms; 150 ms leaves margin without
# discarding real syllables.
MIN_VOICED_S = 0.15
MERGE_GAP_S = 0.12
MIN_PAUSE_S = 0.25


@dataclass(frozen=True)
class Span:
    start: float
    end: float


def frame_flags(audio: np.ndarray) -> list[bool]:
    """Per-30 ms voiced flags for float mono 16 kHz audio; a trailing partial frame is dropped."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    size = SAMPLE_RATE * FRAME_MS // 1000 * 2
    vad = webrtcvad.Vad(AGGRESSIVENESS)
    return [vad.is_speech(pcm[i:i + size], SAMPLE_RATE)
            for i in range(0, len(pcm) - size + 1, size)]


def voiced_runs(flags: list[bool], hangover_frames: int = HANGOVER_FRAMES) -> list[Span]:
    trimmed = []
    start = None
    for i, voiced in enumerate([*flags, False]):
        if voiced and start is None:
            start = i
        elif not voiced and start is not None:
            trimmed.append(Span(start * FRAME_S, max(start, i - hangover_frames) * FRAME_S))
            start = None
    merged = []
    for run in trimmed:
        if merged and run.start - merged[-1].end < MERGE_GAP_S:
            merged[-1] = Span(merged[-1].start, run.end)
        else:
            merged.append(run)
    return [r for r in merged if r.end - r.start >= MIN_VOICED_S]


def speech_span(runs: list[Span]) -> Span | None:
    return Span(runs[0].start, runs[-1].end) if runs else None


def pauses(runs: list[Span]) -> list[Span]:
    gaps = (Span(a.end, b.start) for a, b in zip(runs, runs[1:]))
    return [g for g in gaps if g.end - g.start >= MIN_PAUSE_S]
