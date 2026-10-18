import shutil
import subprocess

import numpy as np
import pytest

from patient_memory.speech.asr import Word, transcribe
from patient_memory.speech.audio import load_pcm, normalize
from patient_memory.speech.prosody import f0_median_hz
from patient_memory.speech.quality import assess, clipping_fraction, on_script_tokens, snr_db
from patient_memory.speech.vad import SAMPLE_RATE, Span, frame_flags, voiced_runs
from tests.unit.synthetic_audio import clip


def words(*tokens):
    return [Word(t, i * 0.3, i * 0.3 + 0.25) for i, t in enumerate(tokens)]


def test_clipping_fraction_counts_samples_at_099_or_more_either_sign():
    audio = np.zeros(1000, dtype=np.float32)
    audio[:7] = 0.99
    audio[7:10] = -1.0
    audio[10:20] = 0.98  # just under the threshold
    assert clipping_fraction(audio) == pytest.approx(10 / 1000)


def test_snr_is_voiced_over_unvoiced_energy_in_db():
    rng = np.random.default_rng(0)
    first, last = round(1.02 * SAMPLE_RATE), 3 * SAMPLE_RATE  # on the 30 ms frame grid
    t = np.arange(first, last) / SAMPLE_RATE
    audio = 0.1 * rng.standard_normal(4 * SAMPLE_RATE)  # noise floor, rms 0.1
    audio[first:last] += 0.6 * np.sin(2 * np.pi * 200 * t)
    # Voiced rms^2 = 0.1^2 + 0.6^2 / 2 = 0.19, unvoiced 0.01: 10 * log10(19) = 12.8 dB.
    assert snr_db(audio.astype(np.float32), [Span(1.02, 3.0)]) == pytest.approx(12.8, abs=0.3)


def test_snr_is_unknown_without_voiced_or_unvoiced_frames():
    audio = np.ones(SAMPLE_RATE, dtype=np.float32) * 0.1
    assert snr_db(audio, []) is None
    assert snr_db(audio, [Span(0.0, 1.0)]) is None


def test_on_script_tokens_are_distinct_and_survive_whisper_formatting():
    spoken = words("1,", "2,", "-3", "four", "Twenty.", "20", "Monday,", "tuesday.", "Sunday")
    # 1, 2, 3, 4, 20, monday, tuesday, sunday ("20" and "Twenty." are the same token)
    assert on_script_tokens(spoken) == 8


def test_off_script_words_and_out_of_range_numbers_do_not_count():
    assert on_script_tokens(words("21", "hello", "12345678910.", "Funday", "0")) == 0


SCRIPT = [str(n) for n in range(1, 21)] + ["Monday", "Tuesday", "Wednesday", "Thursday",
                                          "Friday", "Saturday", "Sunday"]
GOOD_PLAN = [("s", 0.3), ("v", 2.5), ("s", 0.6), ("v", 2.5), ("s", 0.6), ("v", 2.5), ("s", 0.3)]


def check(audio, spoken=SCRIPT):
    return assess(audio, words(*spoken), voiced_runs(frame_flags(audio)))


def test_a_clean_on_script_clip_is_usable():
    result = check(clip(GOOD_PLAN))
    assert (result.usable, result.reasons) == (True, ())


def test_short_clip():
    # 5.5 s long with 5.2 s of speech: only the duration check fails.
    assert check(clip([("s", 0.15), ("v", 5.2), ("s", 0.15)])).reasons == ("too_short",)


def test_too_little_voiced_speech():
    # 8 s long but only 4.5 s voiced.
    plan = [("s", 0.3), ("v", 2.0), ("s", 3.0), ("v", 2.5), ("s", 0.3)]
    result = check(clip(plan))
    assert (result.usable, result.reasons) == (False, ("too_little_speech",))


def test_too_few_words():
    assert check(clip(GOOD_PLAN), SCRIPT[:14]).reasons == ("too_few_words",)
    assert check(clip(GOOD_PLAN), SCRIPT[:15]).reasons == ()


def test_noisy_clip():
    audio = clip(GOOD_PLAN)
    noise = 0.25 * np.random.default_rng(1).standard_normal(len(audio)).astype(np.float32)
    assert "too_noisy" in check(audio + noise).reasons


def test_clipped_clip():
    assert check(np.clip(clip(GOOD_PLAN) * 8, -1, 1)).reasons == ("clipped",)


def test_off_script_clip():
    chatter = ("the quick brown fox jumps over the lazy dog while nobody is counting "
               "anything at all today").split()
    assert check(clip(GOOD_PLAN), chatter).reasons == ("off_script",)
    assert check(clip(GOOD_PLAN), SCRIPT[:9] + chatter).reasons == ("off_script",)


def test_every_failing_reason_is_reported_in_table_order():
    result = check(clip([("s", 0.5)]), ["hello"])
    assert result.reasons == ("too_short", "too_little_speech", "too_few_words", "off_script")


@pytest.mark.parametrize("snr,ordinary,venue", [
    (10.01, True, True), (9.99, False, True), (7.01, False, True), (6.99, False, False),
])
def test_loud_venue_accepts_exactly_three_db_more_noise(snr, ordinary, venue):
    # Known frame-aligned energy ratio; actual SNR calculation, no audio/model network.
    audio = np.full(round(7.2 * SAMPLE_RATE), .02, dtype=np.float32)
    audio[round(.6 * SAMPLE_RATE):round(6.6 * SAMPLE_RATE)] *= np.sqrt(10 ** (snr / 10))
    runs = [Span(.6, 6.6)]
    assert snr_db(audio, runs) == pytest.approx(snr, abs=.001)
    spoken = words(*SCRIPT)
    assert assess(audio, spoken, runs).usable is ordinary
    assert assess(audio, spoken, runs, loud_venue=True).usable is venue


def test_loud_venue_keeps_every_other_gate_and_unknown_noise_rejection():
    audio = np.zeros(SAMPLE_RATE, dtype=np.float32)
    result = assess(audio, [], [Span(0, 1)], loud_venue=True)
    assert result.reasons == ("too_short", "too_little_speech", "too_few_words",
                              "too_noisy", "off_script")
    assert assess(np.clip(clip(GOOD_PLAN) * 8, -1, 1), words(*SCRIPT),
                  [Span(.3, 2.8), Span(3.4, 5.9), Span(6.5, 9)],
                  loud_venue=True).reasons == ("clipped",)


@pytest.mark.slow
@pytest.mark.skipif(shutil.which("say") is None or shutil.which("ffmpeg") is None,
                    reason="needs macOS say and ffmpeg")
def test_spoken_prompt_passes_the_whole_chain_with_real_whisper(tmp_path):
    numbers = ("one two three four five six seven eight nine ten eleven twelve thirteen "
               "fourteen fifteen sixteen seventeen eighteen nineteen twenty").split()
    prompt = (", ".join(numbers) + ". Monday, Tuesday, Wednesday, Thursday, "
              "Friday, Saturday, Sunday.")
    spoken, wav = tmp_path / "prompt.aiff", tmp_path / "prompt.wav"
    subprocess.run(["say", "-r", "150", "-o", str(spoken), prompt], check=True)
    normalize(spoken, wav)
    audio = load_pcm(wav)

    heard = transcribe(audio)
    result = assess(audio, heard, voiced_runs(frame_flags(audio)))

    assert on_script_tokens(heard) >= 20  # numerals and punctuation as Whisper wrote them
    assert (result.usable, result.reasons) == (True, ())
    assert 70 < f0_median_hz(audio) < 300
