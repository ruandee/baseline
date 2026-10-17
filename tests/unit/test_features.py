import pytest

from patient_memory.speech.asr import Word
from patient_memory.speech.features import timing_features
from patient_memory.speech.vad import Span, frame_flags, pauses, speech_span, voiced_runs
from tests.unit.synthetic_audio import clip

# Leading/trailing silence is outside the speech span. Four silences are pauses (>= 250 ms);
# the 90 ms gap is a sub-threshold breath that must not count or split the span.
PLAN = [
    ("s", 0.51), ("v", 1.5), ("s", 0.62), ("v", 1.2), ("s", 0.09), ("v", 0.8), ("s", 0.91),
    ("v", 1.8), ("s", 1.19), ("v", 1.5), ("s", 0.31), ("v", 1.0), ("s", 0.6),
]
INNER = PLAN[1:-1]
PAUSES_S = [0.62, 0.91, 1.19, 0.31]
SPAN_S = sum(d for _, d in INNER)


def test_known_silences_give_the_constructed_pause_count_and_ratio():
    runs = voiced_runs(frame_flags(clip(PLAN)))
    features = timing_features([], pauses(runs), speech_span(runs))

    assert len(pauses(runs)) == len(PAUSES_S)
    assert features.pause_ratio == pytest.approx(sum(PAUSES_S) / SPAN_S, rel=0.05)
    assert features.mean_pause_s == pytest.approx(sum(PAUSES_S) / len(PAUSES_S), rel=0.05)


def words(n, start, step):
    return [Word("w", start + i * step, start + (i + 1) * step) for i in range(n)]


def test_speech_rate_is_words_over_first_start_to_last_end_per_minute():
    # 20 words filling 0.5 s..6.5 s: 20 / 6 s * 60 = 200 wpm, regardless of leading silence.
    features = timing_features(words(20, 0.5, 0.3), [], Span(0.0, 7.0))
    assert features.speech_rate_wpm == pytest.approx(200)


def test_no_pauses_means_zero_mean_pause_not_unknown():
    features = timing_features(words(20, 0.5, 0.3), [], Span(0.5, 6.5))
    assert (features.pause_ratio, features.mean_pause_s) == (0.0, 0.0)


def test_undefined_features_are_none_rather_than_zero():
    nothing = timing_features([], [], None)
    assert (nothing.speech_rate_wpm, nothing.pause_ratio, nothing.mean_pause_s) == (None,) * 3
    one_word = timing_features(words(1, 0.5, 0.3), [], Span(0.5, 0.8))
    assert one_word.speech_rate_wpm is None
    assert one_word.pause_ratio == 0.0
