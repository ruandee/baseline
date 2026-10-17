import shutil

import numpy as np
import pytest
import soundfile as sf

from patient_memory.speech.asr import Word
from patient_memory.speech.pipeline import MAX_DURATION_S, InvalidAudio, analyze
from patient_memory.speech.vad import SAMPLE_RATE
from tests.unit.synthetic_audio import clip

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def run(tmp_path, signal, transcribe):
    upload = tmp_path / "upload.wav"
    sf.write(upload, signal, SAMPLE_RATE)
    return analyze(upload, tmp_path, transcribe)


def never(audio):
    raise AssertionError("Whisper must not run on a clip with no voiced speech")


def test_silence_skips_whisper_and_is_unusable_with_undefined_features(tmp_path):
    result = run(tmp_path, clip([("s", 8.0)]), never)

    assert not result.usable and result.words == [] and result.pauses == []
    assert {"too_little_speech", "too_few_words", "off_script"} <= set(result.quality["reasons"])
    assert result.quality["speech_s"] == 0
    assert result.features["speech_rate_wpm"] is None and result.features["pause_ratio"] is None
    assert result.timings_ms.keys() == {"normalize", "vad", "asr", "prosody"}


def test_a_clip_too_short_for_pitch_tracking_leaves_f0_unknown_instead_of_failing(tmp_path):
    result = run(tmp_path, np.zeros(SAMPLE_RATE // 50, dtype=np.float32), never)

    assert not result.usable and "too_short" in result.quality["reasons"]
    assert result.features["f0_median_hz"] is None


def test_timings_cover_every_measured_step_in_whole_milliseconds(tmp_path):
    spoken = [Word("one", 0.5, 0.8)]
    result = run(tmp_path, clip([("s", 0.5), ("v", 3.0)]), lambda audio: spoken)

    assert result.words == spoken
    assert all(isinstance(ms, int) and ms >= 0 for ms in result.timings_ms.values())


def test_a_clip_longer_than_the_prompt_allows_is_refused(tmp_path):
    with pytest.raises(InvalidAudio):
        run(tmp_path, np.zeros((MAX_DURATION_S + 1) * SAMPLE_RATE, dtype=np.float32), never)


def test_a_file_that_is_not_audio_is_refused(tmp_path):
    upload = tmp_path / "upload"
    upload.write_bytes(b"not audio at all")
    with pytest.raises(InvalidAudio):
        analyze(upload, tmp_path, never)
