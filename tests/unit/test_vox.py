"""MOCK Vox encounter adapter: segment arithmetic, consent parsing and resident-only analysis."""
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from patient_memory.baseline.assess import COUNTING_PROMPT, FREE_CONVERSATION, engine_settings
from patient_memory.config import Settings
from patient_memory.domain import VoxSegment
from patient_memory.errors import Problem
from patient_memory.integrations import vox
from patient_memory.speech import vad
from patient_memory.speech.asr import Word
from patient_memory.speech.pipeline import InvalidAudio
from patient_memory.speech.quality import assess
from patient_memory.speech.vad import SAMPLE_RATE
from tests.unit.synthetic_audio import clip, encounter

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures/synthetic/"
                      "vox_encounter_mrs_k.json").read_text(encoding="utf-8"))
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def seg(speaker, start, end, text=None):
    return VoxSegment(speaker=speaker, start=start, end=end, text=text)


def chatter(audio):
    """Twenty free-conversation words spread over the clip, standing in for Whisper."""
    step = (len(audio) / SAMPLE_RATE - 1.0) / 20
    return [Word(f"word{i}", 0.5 + i * step, 0.5 + i * step + 0.8 * step) for i in range(20)]


def never(audio):
    raise AssertionError("Whisper must not run")


def test_staff_and_other_overlap_is_cut_out_of_resident_speech():
    segments = [seg("resident", 0, 10), seg("staff", 2, 3), seg("other", 9, 12),
                seg("resident", 11, 14)]
    assert vox.resident_spans(segments, 20) == [(0, 2), (3, 9), (12, 14)]


def test_resident_spans_merge_clip_to_the_audio_and_drop_slivers():
    segments = [seg("resident", 1, 4), seg("resident", 3, 6), seg("resident", 18, 30),
                seg("resident", 10, 12), seg("staff", 10.03, 12.5)]
    assert vox.resident_spans(segments, 20.0) == [(1, 6), (18, 20.0)]
    assert vox.resident_spans([seg("resident", 25, 30)], 20.0) == []
    assert vox.resident_spans([seg("staff", 0, 20)], 20.0) == []


def test_fixture_expected_resident_speech_matches_its_timeline():
    segments = [VoxSegment(**s) for s in FIXTURE["segments"]]
    spans = vox.resident_spans(segments, 40.0)
    assert sum(e - s for s, e in spans) == pytest.approx(FIXTURE["expected"]["resident_speech_s"])
    assert all(s.speaker == "resident" for s in segments
               if any(a < s.end and s.start < b for a, b in spans))


def test_extract_concatenates_in_order_and_caps_the_length():
    audio = np.arange(10 * SAMPLE_RATE, dtype=np.float32)
    joined, truncated = vox.extract(audio, [(1, 2), (5, 6)])
    assert len(joined) == 2 * SAMPLE_RATE and not truncated
    assert joined[0] == SAMPLE_RATE and joined[SAMPLE_RATE] == 5 * SAMPLE_RATE
    capped, truncated = vox.extract(audio, [(0, 4), (5, 9)], limit_s=6)
    assert len(capped) == 6 * SAMPLE_RATE and truncated


@pytest.mark.parametrize("parts", [None, [], [""], ["false"], ["True"], ["TRUE"], [" true"],
                                   ["true "], ["1"], ["yes"], ["true", "true"],
                                   ["true", "false"], ["false", "true"]])
def test_only_a_single_raw_true_is_consent(parts):
    assert vox.consent_given(parts) is False


def test_true_is_consent():
    assert vox.consent_given(["true"]) is True


@pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]",
                                 json.dumps([{"speaker": "nurse", "start": 0, "end": 1}]),
                                 json.dumps([{"speaker": "resident", "start": 2, "end": 1}]),
                                 json.dumps([{"speaker": "resident", "start": -1, "end": 1}]),
                                 json.dumps([{"speaker": "resident", "start": 0, "end": 1,
                                              "extra": 1}]),
                                 json.dumps([{"speaker": "resident", "start": 0, "end": 1}] * 401)])
def test_malformed_segments_are_a_422_that_echoes_nothing(raw):
    with pytest.raises(Problem) as caught:
        vox.parse_segments(raw)
    assert (caught.value.status, caught.value.code) == (422, "invalid_request")


def test_encounter_ts_must_be_aware_and_not_in_the_future():
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    assert vox.parse_encounter_ts("2026-10-17T11:00:00Z", now) == now - timedelta(hours=1)
    for raw in [None, "yesterday", "2026-10-17T11:00:00", "2026-10-17T12:10:00Z"]:
        with pytest.raises(Problem):
            vox.parse_encounter_ts(raw, now)


def test_free_conversation_skips_the_on_script_gate_only():
    audio = clip([("s", 0.6)] + [("v", 1.4), ("s", 0.4)] * 5)
    runs = vad.voiced_runs(vad.frame_flags(audio))
    words = chatter(audio)
    assert assess(audio, words, runs).reasons == ("off_script",)
    assert assess(audio, words, runs, on_script=False).usable
    assert "too_few_words" in assess(audio, words[:3], runs, on_script=False).reasons


def test_free_conversation_uses_its_own_threshold():
    cfg = Settings(z_threshold=2.0, z_threshold_free=2.5)
    assert engine_settings(cfg, FREE_CONVERSATION).z_threshold == 2.5
    assert engine_settings(cfg, COUNTING_PROMPT).z_threshold == 2.0
    assert cfg.z_threshold == 2.0  # the shared settings object is not mutated
    with pytest.raises(ValueError):
        Settings(z_threshold_free=0)


def write(tmp_path, signal):
    upload = tmp_path / "upload.wav"
    sf.write(upload, signal, SAMPLE_RATE)
    return upload


@needs_ffmpeg
def test_fixture_encounter_analyzes_resident_speech_only(tmp_path):
    heard = []

    def transcribe(audio):
        heard.append(len(audio) / SAMPLE_RATE)
        return chatter(audio)

    segments = [VoxSegment(**s) for s in FIXTURE["segments"]]
    upload = write(tmp_path, encounter(FIXTURE["segments"]))
    result = vox.analyze_encounter(upload, tmp_path, segments, transcribe)

    assert result.analysis.usable, result.analysis.quality
    assert 8 <= result.resident_speech_s < result.analyzed_s
    assert result.resident_speech_s == pytest.approx(result.analysis.quality["speech_s"])
    assert heard == [pytest.approx(result.analyzed_s, abs=0.01)]
    assert result.counts == {"resident": 3, "staff": 3, "other": 1}
    # Staff (230 Hz) and the other speaker (190 Hz) would pull this well away from 140 Hz.
    assert result.analysis.features["f0_median_hz"] == pytest.approx(140, rel=0.05)
    assert "extract" in result.analysis.timings_ms and not result.truncated


@needs_ffmpeg
def test_too_little_resident_speech_is_unusable_and_never_transcribed(tmp_path):
    plan = [{"speaker": "staff", "start": 0, "end": 10}, {"speaker": "resident", "start": 10,
                                                          "end": 17.5}]
    upload = write(tmp_path, encounter(plan))
    result = vox.analyze_encounter(upload, tmp_path, [VoxSegment(**s) for s in plan], never)
    assert not result.analysis.usable
    assert result.analysis.quality["reasons"] == ["too_little_resident_speech"]
    assert result.analysis.features["speech_rate_wpm"] is None


@needs_ffmpeg
def test_long_resident_turn_with_less_than_eight_seconds_of_voice_never_transcribes(tmp_path):
    audio = clip([("v", 4), ("s", 16)])
    result = vox.analyze_encounter(write(tmp_path, audio), tmp_path,
                                   [seg("resident", 0, 20)], never)
    assert not result.analysis.usable
    assert result.analyzed_s == 20
    assert result.resident_speech_s < 8
    assert result.analysis.quality["reasons"] == ["too_little_resident_speech"]


@needs_ffmpeg
def test_an_encounter_longer_than_the_limit_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(vox, "MAX_ENCOUNTER_S", 5)
    upload = write(tmp_path, np.zeros(7 * SAMPLE_RATE, dtype=np.float32))
    with pytest.raises(InvalidAudio):
        vox.analyze_encounter(upload, tmp_path, [seg("resident", 0, 7)], never)
