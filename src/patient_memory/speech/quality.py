import re
from dataclasses import dataclass

import numpy as np

from patient_memory.speech.asr import Word
from patient_memory.speech.vad import FRAME_MS, FRAME_S, SAMPLE_RATE, Span

MIN_DURATION_S = 6.0
MIN_SPEECH_S = 5.0
MIN_WORDS = 15
MIN_SNR_DB = 10.0
LOUD_VENUE_SNR_DB = MIN_SNR_DB - 3.0
MAX_CLIPPED = 0.01
CLIP_LEVEL = 0.99
MIN_ON_SCRIPT = 10
NUMBER_WORDS = ("one two three four five six seven eight nine ten eleven twelve thirteen "
                "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
NUMBERS = {word: str(n) for n, word in enumerate(NUMBER_WORDS, start=1)}
DAYS = ("monday tuesday wednesday thursday friday saturday sunday").split()
EXPECTED = set(NUMBERS.values()) | set(DAYS)


def clipping_fraction(audio: np.ndarray) -> float:
    return float(np.mean(np.abs(audio) >= CLIP_LEVEL)) if len(audio) else 0.0


def snr_db(audio: np.ndarray, runs: list[Span]) -> float | None:
    """Mean energy of frames inside voiced runs over the rest, in dB; None if either is empty."""
    size = SAMPLE_RATE * FRAME_MS // 1000
    frames = audio[:len(audio) // size * size].reshape(-1, size).astype(np.float64)
    energy = (frames ** 2).mean(axis=1)
    centers = (np.arange(len(energy)) + 0.5) * FRAME_S
    voiced = np.zeros(len(energy), dtype=bool)
    for run in runs:
        voiced |= (centers >= run.start) & (centers < run.end)
    if not voiced.any() or voiced.all():
        return None
    return float(10 * np.log10(energy[voiced].mean() / max(energy[~voiced].mean(), 1e-12)))


def on_script_tokens(words: list[Word]) -> int:
    """Distinct prompt tokens (1 to 20, Monday to Sunday) heard, whether Whisper wrote the
    number as a digit ("1,", "-2") or a word ("one")."""
    heard = {re.sub(r"[^a-z0-9]", "", w.w.lower()) for w in words}
    return len({NUMBERS.get(token, token) for token in heard} & EXPECTED)


@dataclass(frozen=True)
class Quality:
    usable: bool
    reasons: tuple[str, ...]


def assess(audio: np.ndarray, words: list[Word], runs: list[Span],
           on_script: bool = True, *, loud_venue: bool = False) -> Quality:
    """Gate a 16 kHz mono clip, its transcript and its voiced runs (vad.voiced_runs).

    `on_script=False` skips the prompt-token check, for free conversation (Vox encounters).

    Reason codes come back in spec-table order. Unusable checks are stored for audit but never
    reach the baselines or the change engine.
    """
    snr = snr_db(audio, runs)
    failed = {
        "too_short": len(audio) / SAMPLE_RATE < MIN_DURATION_S,
        "too_little_speech": sum(r.end - r.start for r in runs) < MIN_SPEECH_S,
        "too_few_words": len(words) < MIN_WORDS,
        # No quiet frame at all means the VAD heard speech everywhere: noise, not headroom.
        "too_noisy": bool(runs) and (
            snr is None or snr < (LOUD_VENUE_SNR_DB if loud_venue else MIN_SNR_DB)),
        "clipped": clipping_fraction(audio) >= MAX_CLIPPED,
        "off_script": on_script and on_script_tokens(words) < MIN_ON_SCRIPT,
    }
    reasons = tuple(code for code, bad in failed.items() if bad)
    return Quality(usable=not reasons, reasons=reasons)
