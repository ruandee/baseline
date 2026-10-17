import pytest

from patient_memory.speech.vad import FRAME_S, pauses, speech_span, voiced_runs


def flags(pattern):
    return [c == "#" for c in pattern]


def test_startup_burst_is_not_speech():
    # With any noise floor webrtcvad flags the first 3 frames; it must not start the span.
    runs = voiced_runs(flags("###" + "." * 14 + "#" * 20))
    assert [(r.start, r.end) for r in runs] == [
        (pytest.approx(17 * FRAME_S), pytest.approx(33 * FRAME_S)),
    ]


def test_runs_closer_than_120_ms_merge():
    # 3 frames = 90 ms merges, 5 frames = 150 ms stays split (hangover off to isolate the rule).
    merged = voiced_runs(flags("#" * 10 + "." * 3 + "#" * 10), hangover_frames=0)
    split = voiced_runs(flags("#" * 10 + "." * 5 + "#" * 10), hangover_frames=0)
    assert [(r.start, r.end) for r in merged] == [
        (pytest.approx(0), pytest.approx(23 * FRAME_S))]
    assert len(split) == 2


def test_hangover_is_trimmed_from_the_end_of_every_run():
    # webrtcvad keeps reporting voice for 4 frames (120 ms) after speech stops.
    runs = voiced_runs(flags("#" * 10 + "." * 8 + "#" * 10))
    assert [(r.start, r.end) for r in runs] == [
        (pytest.approx(0), pytest.approx(6 * FRAME_S)),
        (pytest.approx(18 * FRAME_S), pytest.approx(24 * FRAME_S)),
    ]


def test_pause_is_an_unvoiced_gap_of_250_ms_or_more_inside_the_speech_span():
    short = voiced_runs(flags("#" * 10 + "." * 8 + "#" * 10), hangover_frames=0)  # 240 ms
    long = voiced_runs(flags("#" * 10 + "." * 9 + "#" * 10), hangover_frames=0)  # 270 ms
    assert pauses(short) == []
    assert [(p.start, p.end) for p in pauses(long)] == [
        (pytest.approx(10 * FRAME_S), pytest.approx(19 * FRAME_S))]


def test_speech_span_runs_from_first_to_last_voiced_frame_and_leading_silence_is_not_a_pause():
    pattern = "." * 20 + "#" * 10 + "." * 9 + "#" * 10 + "." * 30
    runs = voiced_runs(flags(pattern), hangover_frames=0)
    span = speech_span(runs)
    assert (span.start, span.end) == (pytest.approx(20 * FRAME_S), pytest.approx(49 * FRAME_S))
    assert len(pauses(runs)) == 1


def test_no_voiced_frames_means_no_span_and_no_pauses():
    runs = voiced_runs(flags("." * 40))
    assert speech_span(runs) is None
    assert pauses(runs) == []
