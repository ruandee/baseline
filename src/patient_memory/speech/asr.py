from dataclasses import dataclass
from functools import cache

import numpy as np

from patient_memory.config import settings


@dataclass(frozen=True)
class Word:
    w: str
    start: float
    end: float


@cache
def model():
    # Imported here so importing this module never loads ctranslate2 or reaches Hugging Face.
    from faster_whisper import WhisperModel

    return WhisperModel(settings().whisper_model, compute_type="int8")


def transcribe(audio: np.ndarray) -> list[Word]:
    """Words with timestamps from 16 kHz mono float audio (see audio.load_pcm).

    Passing the array, not a path, keeps faster-whisper from decoding the file again through
    av, whose unbounded dependency range broke it (av 19 rejects its metadata_errors option).
    """
    segments, _ = model().transcribe(
        audio, beam_size=1, language="en", word_timestamps=True, vad_filter=False)
    # segments is a lazy generator: decoding only happens while it is consumed.
    # ctranslate2 yields numpy scalars; plain floats keep them out of JSON and the database.
    return [Word(w.word.strip(), float(w.start), float(w.end))
            for s in segments for w in s.words or []]
