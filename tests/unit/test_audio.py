import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from patient_memory.speech.audio import load_pcm, normalize

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def amplitude_at(signal, hz, rate=16000):
    spectrum = np.abs(np.fft.rfft(signal)) / (len(signal) / 2)
    return spectrum[round(hz * len(signal) / rate)]


@needs_ffmpeg
def test_normalize_gives_16k_mono_with_low_rumble_removed(tmp_path):
    t = np.arange(2 * 44100) / 44100
    mix = 0.3 * np.sin(2 * np.pi * 30 * t) + 0.3 * np.sin(2 * np.pi * 1000 * t)
    src, dst = tmp_path / "in.wav", tmp_path / "out.wav"
    sf.write(src, np.stack([mix, mix], axis=1), 44100)

    normalize(src, dst)
    pcm = load_pcm(dst)

    assert pcm.ndim == 1 and pcm.dtype == np.float32
    assert len(pcm) == pytest.approx(2 * 16000, abs=400)
    assert amplitude_at(pcm, 1000) == pytest.approx(0.3, rel=0.1)
    assert amplitude_at(pcm, 30) < 0.25 * amplitude_at(pcm, 1000)


@needs_ffmpeg
def test_normalize_rejects_a_file_that_is_not_audio(tmp_path):
    src = tmp_path / "in.webm"
    src.write_bytes(b"not audio at all")
    with pytest.raises(subprocess.CalledProcessError):
        normalize(src, tmp_path / "out.wav")


def test_load_pcm_refuses_anything_but_16k_mono(tmp_path):
    wrong_rate = tmp_path / "rate.wav"
    sf.write(wrong_rate, np.zeros(4410), 44100)
    stereo = tmp_path / "stereo.wav"
    sf.write(stereo, np.zeros((1600, 2)), 16000)
    for path in (wrong_rate, stereo):
        with pytest.raises(ValueError):
            load_pcm(path)
