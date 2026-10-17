from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from patient_memory.baseline.engine import Check, evaluate
from patient_memory.config import Settings

NOW = datetime(2026, 10, 17, 9, tzinfo=UTC)
CFG = Settings()
JITTER = [0, 1, -1, 2, -2, 1, -1, 0, 2, -2]


def check(hours_ago=0, *, n=0, wpm=140.0, pause=0.20, mean=0.40, f0=150.0, **kw):
    """Feature values sit near the arguments; n picks a small repeatable wobble."""
    j = JITTER[n % len(JITTER)]
    fields = dict(id=f"c{hours_ago}-{n}", ts=NOW - timedelta(hours=hours_ago),
                  device_id="tablet-1", prompt_version="count20-days-v1",
                  is_baseline=False, usable=True)
    fields.update(kw)
    return Check(features={"speech_rate_wpm": wpm + j, "pause_ratio": pause + 0.003 * j,
                           "mean_pause_s": mean + 0.01 * j, "f0_median_hz": f0 + j}, **fields)


def daily(count, **kw):
    """`count` stable checks, one a day, ending two days before NOW."""
    return [check(48 + 24 * (count - 1 - i), n=i, **kw) for i in range(count)]


def drifted(hours_ago=0, dz=3.5, **kw):
    """Slower, more pausing, by `dz` robust-scale units on three features (scales for the
    stable history: 7 wpm, 0.02 ratio, 0.05 s)."""
    return check(hours_ago, wpm=140 - 7 * dz, pause=0.20 + 0.02 * dz, mean=0.40 + 0.05 * dz, **kw)


def test_fewer_than_three_baseline_checks_is_enrolling_without_scores():
    assessment = evaluate(check(), daily(2), "rolling", CFG)
    assert assessment.status == "enrolling"
    assert assessment.features == {}


def test_stable_speech_against_a_rolling_baseline_is_none():
    assessment = evaluate(check(n=3), daily(10), "rolling", CFG)
    assert assessment.status == "none"
    assert set(assessment.features) == {"speech_rate_wpm", "pause_ratio", "mean_pause_s",
                                        "f0_median_hz"}
    assert abs(assessment.fused) < 1


def test_one_strong_clip_is_provisional():
    assessment = evaluate(drifted(), daily(10), "rolling", CFG)
    assert assessment.status == "provisional"
    assert assessment.features["speech_rate_wpm"].dz > 3


def test_the_same_drift_on_a_second_check_within_a_day_is_change():
    history = daily(10) + [drifted(2)]
    assert evaluate(drifted(), history, "rolling", CFG).status == "change"


def test_two_mild_checks_confirm_each_other_only_within_a_day():
    mild = dict(dz=2.4)
    assert evaluate(drifted(**mild), daily(10) + [drifted(2, **mild)], "rolling",
                    CFG).status == "change"
    assert evaluate(drifted(**mild), daily(10) + [drifted(26, **mild)], "rolling",
                    CFG).status == "none"


def test_three_fresh_baseline_clips_are_enough_in_enrolled_mode():
    fresh = [check(1 + i / 10, n=i, is_baseline=True) for i in range(3)]
    # Inside the 12 h guard, so rolling mode has no baseline yet.
    assert evaluate(check(n=4), fresh, "rolling", CFG).status == "enrolling"
    assert evaluate(check(n=4), fresh, "enrolled", CFG).status == "none"
    assert evaluate(drifted(), fresh, "enrolled", CFG).status == "provisional"


def test_enrolled_mode_ignores_checks_not_marked_as_baseline():
    # Faster, fewer pauses: not concerning itself, but it would drag a pooled median.
    noise = [check(30 + i, n=i, wpm=190.0, pause=0.10, mean=0.20) for i in range(10)]
    fresh = [check(1 + i / 10, n=i, is_baseline=True) for i in range(3)]
    assert evaluate(check(n=4), noise + fresh, "enrolled", CFG).status == "none"


def test_faster_speech_with_fewer_pauses_is_not_concerning():
    assessment = evaluate(check(wpm=180.0, pause=0.10, mean=0.20), daily(10), "rolling", CFG)
    assert assessment.status == "none"
    assert assessment.features["speech_rate_wpm"].z > 3
    assert assessment.features["speech_rate_wpm"].dz < 0
    assert assessment.features["pause_ratio"].dz < 0


def test_pitch_is_two_sided():
    for f0 in (190.0, 110.0):
        assessment = evaluate(check(f0=f0), daily(10), "rolling", CFG)
        assert assessment.features["f0_median_hz"].dz > 3


def test_worked_scores_with_zero_mad_use_the_absolute_floors():
    baseline = [check(5 + i, n=0, is_baseline=True) for i in range(3)]
    assessment = evaluate(check(wpm=126.0, n=0), baseline, "enrolled", CFG)
    rate = assessment.features["speech_rate_wpm"]
    # scale = max(0, 0.05 * 140, 5) = 7, so (126 - 140) / 7 = -2 and slower is concerning.
    assert (rate.median, rate.scale, rate.z, rate.dz) == (140.0, 7.0, -2.0, 2.0)
    # Baseline clips score 0, so e = 0.3 * 2 + 0.7 * 0 and S = max(0, 0 + 2 - 0.5).
    assert rate.ewma == 0.6 and rate.cusum == 1.5
    assert assessment.features["pause_ratio"].scale == 0.02
    assert assessment.features["mean_pause_s"].scale == 0.05
    assert assessment.features["f0_median_hz"].scale == 7.5
    assert assessment.fused == 0.5


def test_baseline_prefers_the_same_device():
    other = [check(48 + 24 * i, n=i, device_id="tablet-2", wpm=100.0) for i in range(8)]
    own = [check(30 + 24 * i, n=i) for i in range(5)]
    assessment = evaluate(check(), other + own, "rolling", CFG)
    assert assessment.status == "none"
    assert set(assessment.baseline_ids) == {c.id for c in own}


def test_baseline_falls_back_to_all_devices_with_fewer_than_three_matching():
    other = [check(48 + 24 * i, n=i, device_id="tablet-2") for i in range(8)]
    own = [check(30 + 24 * i, n=i) for i in range(2)]
    assessment = evaluate(check(), other + own, "rolling", CFG)
    assert set(assessment.baseline_ids) == {c.id for c in other + own}


def test_baselines_only_use_checks_with_the_same_prompt_version():
    conversation = daily(10, prompt_version="free-conversation-v1")
    assert evaluate(check(), conversation, "rolling", CFG).status == "enrolling"
    mixed = conversation + daily(3)
    assert len(evaluate(check(), mixed, "rolling", CFG).baseline_ids) == 3


def test_unusable_checks_never_enter_the_baseline():
    unusable = [check(48 + i, n=i, usable=False, wpm=60.0) for i in range(10)]
    assert evaluate(check(), unusable + daily(3), "rolling", CFG).status == "none"
    assert evaluate(check(), unusable, "rolling", CFG).status == "enrolling"


def test_rolling_baseline_is_the_last_ten_checks_from_30_days_excluding_12_hours():
    recent = [check(6, n=1, wpm=100.0)]  # inside the 12 h guard
    old = [check(24 * 31 + i, n=i, wpm=100.0) for i in range(5)]  # outside the 30 day window
    fifteen = [check(48 + 24 * i, n=i) for i in range(15)]
    assessment = evaluate(check(), old + fifteen + recent, "rolling", CFG)
    assert set(assessment.baseline_ids) == {c.id for c in fifteen[:10]}  # the newest ten


def test_sustained_small_drift_trips_cusum_without_two_consecutive_alarms():
    baseline = [check(400 + i, n=i, is_baseline=True) for i in range(3)]
    slow = [drifted(30 * k, dz=1.8) for k in range(4, 0, -1)]  # spaced beyond 24 h
    assessment = evaluate(drifted(dz=1.8), baseline + slow, "enrolled", CFG)
    assert all(s.dz < 2 for s in assessment.features.values())
    assert assessment.features["speech_rate_wpm"].cusum >= 4.0
    assert assessment.status == "change"


def test_thresholds_come_from_settings_and_are_echoed():
    pair = daily(10) + [drifted(2, dz=1.8)]
    assert evaluate(drifted(dz=1.8), pair, "rolling", CFG).status == "none"
    cfg = Settings(z_threshold=1.5, cusum_h=9.0)
    assessment = evaluate(drifted(dz=1.8), pair, "rolling", cfg)
    assert assessment.status == "change"
    assert assessment.params["z_threshold"] == 1.5
    assert assessment.params["cusum_h"] == 9.0
    assert assessment.params["mode"] == "rolling"


def test_an_unusable_check_is_refused():
    with pytest.raises(ValueError):
        evaluate(check(usable=False), daily(10), "rolling", CFG)


def test_a_baseline_without_values_for_any_feature_is_still_enrolling():
    blank = {name: None for name in ("speech_rate_wpm", "pause_ratio", "mean_pause_s",
                                     "f0_median_hz")}
    history = [replace(c, features=blank) for c in daily(10)]
    assert evaluate(check(), history, "rolling", CFG).status == "enrolling"


def test_every_parameter_used_is_echoed():
    params = evaluate(check(), daily(10), "rolling", CFG).params
    assert params["mad_scale"] == 1.4826 and params["relative_floor"] == 0.05
    assert params["absolute_floors"]["f0_median_hz"] == 5.0
    assert params["directions"]["speech_rate_wpm"] == -1
    assert (params["rolling_checks"], params["rolling_window_days"]) == (10, 30)
    assert (params["rolling_guard_hours"], params["consecutive_hours"]) == (12, 24)
