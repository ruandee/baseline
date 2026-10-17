import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from patient_memory.speech.vad import SAMPLE_RATE


def normalize(src: Path, dst: Path, timeout_s: float = 30) -> None:
    """Decode any browser recording to 16 kHz mono wav with the 80 Hz high-pass.

    File to file on purpose: mp4 (index at the end) demuxes most reliably from a seekable input.
    The whitelist keeps a crafted upload (HLS or concat playlist) from making ffmpeg open URLs.
    The caller owns both files and deletes them.
    """
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-protocol_whitelist", "file", "-y", "-i", str(src),
         "-ac", "1", "-ar", str(SAMPLE_RATE), "-af", "highpass=f=80", "-f", "wav", str(dst)],
        check=True, capture_output=True, timeout=timeout_s,
    )


def load_pcm(path: Path) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32")
    if rate != SAMPLE_RATE or audio.ndim != 1:
        raise ValueError(f"expected {SAMPLE_RATE} Hz mono audio, got {rate} Hz shape {audio.shape}")
    return audio
