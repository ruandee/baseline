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


def decode(upload: Path, wav: Path, max_seconds: float | None = None) -> np.ndarray:
    normalize(upload, wav, max_seconds=max_seconds)
    return load_pcm(wav)


class Timer:
    """Whole-millisecond wall time per pipeline step, keyed by step name."""

    def __init__(self):
        self.timings: dict[str, int] = {}

    def __call__(self, step, fn, *args):
        started = time.perf_counter()
        result = fn(*args)
        self.timings[step] = round((time.perf_counter() - started) * 1000)
        return result


def decode_upload(upload: Path, work: Path, timer: Timer, max_seconds: float) -> np.ndarray:
    """Decode to 16 kHz mono, refusing what will not decode or runs past `max_seconds`.

    ffmpeg stops one second past the limit, so an over-long upload never decodes in full.
    """
    try:
        audio = timer("normalize", decode, upload, work / "normalized.wav", max_seconds + 1)
    except FileNotFoundError as exc:
        raise DecoderUnavailable from exc
    # A decode that outruns the 30 s timeout is a crafted file, so it is the caller's 422 too.
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, RuntimeError) as exc:
        raise InvalidAudio from exc
    if len(audio) / vad.SAMPLE_RATE > max_seconds:
        raise InvalidAudio
    return audio


def analyze(upload: Path, work: Path,
            transcribe: Callable[[np.ndarray], list[asr.Word]] = asr.transcribe, *,
            loud_venue: bool = False) -> Analysis:
    """Run one recording through normalize, VAD, ASR, prosody and the quality gate.

    `work` is scratch space for the decoded wav; the caller owns both paths and deletes them.
    """
    timer = Timer()
    audio = decode_upload(upload, work, timer, MAX_DURATION_S)
    return analyze_pcm(audio, transcribe, timer, loud_venue=loud_venue)


def analyze_pcm(audio: np.ndarray, transcribe: Callable[[np.ndarray], list[asr.Word]],
                timer: Timer, on_script: bool = True, *, loud_venue: bool = False) -> Analysis:
    """VAD, ASR, prosody and the quality gate on decoded 16 kHz mono audio.

    `on_script=False` is for free conversation, which has no prompt to stay on.
    """
    seconds = len(audio) / vad.SAMPLE_RATE
    runs = timer("vad", lambda: vad.voiced_runs(vad.frame_flags(audio)))
    span, pauses = vad.speech_span(runs), vad.pauses(runs)
    # Whisper invents words for silence, so with no voiced run there is nothing to transcribe.
    words = timer("asr", lambda: transcribe(audio) if runs else [])
    f0 = timer("prosody", f0_or_none, audio)
    gate = assess(audio, words, runs, on_script=on_script, loud_venue=loud_venue)
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
        words=words, pauses=pauses, timings_ms=timer.timings)


def f0_or_none(audio: np.ndarray) -> float | None:
    """Praat refuses clips shorter than a few pitch periods; for those F0 is simply unknown."""
    try:
        return f0_median_hz(audio)
    except parselmouth.PraatError:
        return None
