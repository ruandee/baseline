import numpy as np
import pytest

from patient_memory.speech.prosody import f0_median_hz
from tests.unit.synthetic_audio import SAMPLE_RATE, voiced


@pytest.mark.parametrize("f0", [110.0, 220.0])
def test_median_f0_tracks_the_constructed_pitch(f0):
    assert f0_median_hz(voiced(3, f0=f0).astype(np.float32)) == pytest.approx(f0, rel=0.05)


def test_higher_voice_gives_higher_median():
    low, high = (f0_median_hz(voiced(3, f0=f).astype(np.float32)) for f in (120.0, 200.0))
    assert high > low


def test_no_voiced_frames_is_unknown_not_zero():
    noise = 0.01 * np.random.default_rng(0).standard_normal(3 * SAMPLE_RATE)
    assert f0_median_hz(noise.astype(np.float32)) is None
