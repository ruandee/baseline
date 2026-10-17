import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import parselmouth

from patient_memory.speech import asr, vad
from patient_memory.speech.audio import load_pcm, normalize
from patient_memory.speech.features import timing_features
from patient_memory.speech.prosody import f0_median_hz
from patient_memory.speech.quality import MAX_CLIPPED, assess, clipping_fraction, snr_db

# The prompt auto-stops at 15 s; anything much longer is not a check and would hold a worker in
# Whisper for minutes (2 MB of opus is about 16 minutes).
MAX_DURATION_S = 30


class InvalidAudio(ValueError):
    """The upload is not audio we can decode into a bounded 16 kHz mono clip."""


class DecoderUnavailable(RuntimeError):
    """ffmpeg is not installed, which no upload can fix."""


@dataclass(frozen=True)
class Analysis:
    usable: bool
    quality: dict
    features: dict
    words: list[asr.Word]
    pauses: list[vad.Span]
    timings_ms: dict[str, int]


def decode(upload: Path, wav: Path) -> np.ndarray:
    normalize(upload, wav)
    return load_pcm(wav)


def analyze(upload: Path, work: Path,
            transcribe: Callable[[np.ndarray], list[asr.Word]] = asr.transcribe) -> Analysis:
    """Run one recording through normalize, VAD, ASR, prosody and the quality gate.

    `work` is scratch space for the decoded wav; the caller owns both paths and deletes them.
    """
    timings: dict[str, int] = {}

    def timed(step, fn, *args):
        started = time.perf_counter()
        result = fn(*args)
        timings[step] = round((time.perf_counter() - started) * 1000)
        return result

    try:
        audio = timed("normalize", decode, upload, work / "normalized.wav")
    except FileNotFoundError as exc:
        raise DecoderUnavailable from exc
    # A decode that outruns the 30 s timeout is a crafted file, so it is the caller's 422 too.
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        raise InvalidAudio from exc
    seconds = len(audio) / vad.SAMPLE_RATE
    if seconds > MAX_DURATION_S:
        raise InvalidAudio

    runs = timed("vad", lambda: vad.voiced_runs(vad.frame_flags(audio)))
    span, pauses = vad.speech_span(runs), vad.pauses(runs)
    # Whisper invents words for silence, so with no voiced run there is nothing to transcribe.
    words = timed("asr", lambda: transcribe(audio) if runs else [])
    f0 = timed("prosody", f0_or_none, audio)
    gate = assess(audio, words, runs)
    timing = timing_features(words, pauses, span)
    snr = snr_db(audio, runs)
    return Analysis(
        usable=gate.usable,
        quality={"duration_s": round(seconds, 2),
                 "speech_s": round(sum(r.end - r.start for r in runs), 2),
                 "snr_db": None if snr is None else round(snr, 1),
                 "clipped": clipping_fraction(audio) >= MAX_CLIPPED,
                 "reasons": list(gate.reasons)},
        features={"speech_rate_wpm": timing.speech_rate_wpm, "pause_ratio": timing.pause_ratio,
                  "mean_pause_s": timing.mean_pause_s, "f0_median_hz": f0},
        words=words, pauses=pauses, timings_ms=timings)


def f0_or_none(audio: np.ndarray) -> float | None:
    """Praat refuses clips shorter than a few pitch periods; for those F0 is simply unknown."""
    try:
        return f0_median_hz(audio)
    except parselmouth.PraatError:
        return None
