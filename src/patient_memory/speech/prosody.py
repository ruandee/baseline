import numpy as np
import parselmouth

from patient_memory.speech.vad import SAMPLE_RATE


def f0_median_hz(audio: np.ndarray) -> float | None:
    """Median F0 over Praat-voiced frames of 16 kHz mono audio; None if nothing is voiced."""
    sound = parselmouth.Sound(audio.astype(np.float64), sampling_frequency=SAMPLE_RATE)
    f0 = sound.to_pitch_ac(pitch_floor=75, pitch_ceiling=500).selected_array["frequency"]
    voiced = f0[f0 > 0]
    return float(np.median(voiced)) if voiced.size else None
