"""BL-30 signal-adapter registry: declared features, per-modality status, corroboration.

The speech engine tests in test_engine.py are unchanged; these cover the registry layer.
"""
from datetime import UTC, datetime, timedelta

import pytest

from patient_memory.baseline import engine
from patient_memory.baseline.engine import (
    FEATURES,
    REGISTRY,
    SPEECH,
    Check,
    FeatureSpec,
    Modality,
    ModalityResult,
    combine,
    combined_payload,
    evaluate,
    register,
)
from patient_memory.baseline.verdict import decide
from patient_memory.config import Settings

NOW = datetime(2026, 10, 17, 9, tzinfo=UTC)
CFG = Settings()
JITTER = [0, 1, -1, 2, -2, 1, -1, 0, 2, -2]

# A test-only second modality, registered per test so the global registry stays speech-only.
PROBE = Modality("probe", (
    FeatureSpec("probe_time_s", "probe", 1, 0.2),
    FeatureSpec("probe_sway", "probe", 1, 0.01),
    FeatureSpec("probe_cadence_spm", "probe", -1, 2.0),
))


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setitem(REGISTRY, PROBE.name, PROBE)
    return PROBE


def speech(hours_ago=0, *, n=0, dz=0.0, **kw):
    j = JITTER[n % len(JITTER)]
    return Check(id=f"s{hours_ago}-{n}", ts=NOW - timedelta(hours=hours_ago),
                 device_id="tablet-1", prompt_version="count20-days-v1", is_baseline=False,
                 usable=True, features={"speech_rate_wpm": 140 + j - 7 * dz,
                                        "pause_ratio": 0.20 + 0.003 * j + 0.02 * dz,
                                        "mean_pause_s": 0.40 + 0.01 * j + 0.05 * dz,
                                        "f0_median_hz": 150.0 + j}, **kw)


def probe_check(hours_ago=0, *, n=0, dz=0.0, **kw):
    """Probe scales for the stable history: 0.5 s, 0.01, 5 spm (relative floors)."""
    j = JITTER[n % len(JITTER)]
    return Check(id=f"p{hours_ago}-{n}", ts=NOW - timedelta(hours=hours_ago),
                 device_id="phone-1", prompt_version="probe-v1", is_baseline=False,
                 usable=True, modality="probe",
                 features={"probe_time_s": 10.0 + 0.05 * j + 0.5 * dz,
                           "probe_sway": 0.10 + 0.001 * j + 0.01 * dz,
                           "probe_cadence_spm": 100.0 + j - 5 * dz}, **kw)


def daily(factory, count=10):
    return [factory(48 + 24 * (count - 1 - i), n=i) for i in range(count)]


def result(check, history):
    return ModalityResult(check.modality, check.ts, evaluate(check, history, "rolling", CFG))


def test_speech_is_registered_with_the_original_feature_table():
    assert REGISTRY["speech"] is SPEECH
    assert FEATURES == {"speech_rate_wpm": (-1, 5.0), "pause_ratio": (1, 0.02),
                        "mean_pause_s": (1, 0.05), "f0_median_hz": (0, 5.0)}
    params = evaluate(speech(), daily(speech), "rolling", CFG).params
    assert params["modality"] == "speech"
    assert params["directions"] == {n: d for n, (d, _) in FEATURES.items()}
    assert params["min_features"] == CFG.min_features


def test_registry_rejects_conflicting_or_invalid_declarations(monkeypatch):
    monkeypatch.setattr(engine, "REGISTRY", dict(REGISTRY))
    with pytest.raises(ValueError):
        register(SPEECH)
    with pytest.raises(ValueError):  # a feature can belong to one modality only
        register(Modality("copy", (FeatureSpec("pause_ratio", "copy", 1, 0.02),)))
    with pytest.raises(ValueError):
        FeatureSpec("x", "m", 2, 1.0)
    with pytest.raises(ValueError):
        FeatureSpec("x", "m", 1, 0.0)
    with pytest.raises(ValueError):
        Modality("m", (FeatureSpec("x", "other", 1, 1.0),))
    with pytest.raises(ValueError):
        Modality("m", (FeatureSpec("x", "m", 1, 1.0),), cusum_min_features=2)
    assert register(Modality("solo", (FeatureSpec("solo_x", "solo", 1, 1.0),),
                             min_features=1, cusum_min_features=1)).name == "solo"


def test_a_registered_modality_is_scored_on_its_own_features(probe):
    stable = evaluate(probe_check(n=3), daily(probe_check), "rolling", CFG)
    assert stable.status == "none"
    assert set(stable.features) == {"probe_time_s", "probe_sway", "probe_cadence_spm"}
    assert stable.params["modality"] == "probe"
    assert stable.params["directions"]["probe_cadence_spm"] == -1
    assert evaluate(probe_check(dz=3.5), daily(probe_check), "rolling", CFG).status == \
        "provisional"


def test_histories_of_different_modalities_never_mix(probe):
    # Probe checks in the speech history (and the reverse) are ignored entirely.
    assert evaluate(speech(), daily(probe_check) + daily(speech, 2), "rolling",
                    CFG).status == "enrolling"
    assert evaluate(probe_check(), daily(speech) + daily(probe_check, 2), "rolling",
                    CFG).status == "enrolling"
    pure = evaluate(speech(dz=3.5), daily(speech), "rolling", CFG)
    with_probe = evaluate(speech(dz=3.5), daily(speech) + [probe_check(2, dz=3.5)],
                          "rolling", CFG)
    assert pure == with_probe


def test_two_provisional_modalities_within_a_day_are_corroborated_and_read_as_change(probe):
    voice = result(speech(dz=3.5), daily(speech))
    motion = result(probe_check(3, dz=3.5), daily(probe_check))
    assert voice.assessment.status == motion.assessment.status == "provisional"
    combined = combine([voice, motion], NOW)
    assert combined.corroborated is True
    assert combined.status == "provisional"
    assert combined.verdict_status == "change"
    assert combined.current == ("probe", "speech")
    # The verdict table sees change: an unexplained corroborated provisional is not a recheck.
    assert decide(combined.verdict_status, combined.fused, []).action != "recheck_1h"
    assert decide(combined.status, combined.fused, []).action == "recheck_1h"
    payload = combined_payload(combined)
    assert payload["corroborated"] is True
    assert {"speech", "probe"} <= set(payload["modalities"])
    assert set(payload["modalities"]["probe"]["per_feature"]) == {
        "probe_time_s", "probe_sway", "probe_cadence_spm"}


def test_speech_alone_is_never_corroborated_and_keeps_its_status():
    for current in (speech(n=3), speech(dz=3.5)):
        voice = result(current, daily(speech))
        combined = combine([voice], NOW)
        assert combined.corroborated is False
        assert combined.status == combined.verdict_status == voice.assessment.status
        assert combined.fused == voice.assessment.fused


def test_one_flagged_modality_and_one_quiet_one_is_not_corroborated(probe):
    voice = result(speech(dz=3.5), daily(speech))
    motion = result(probe_check(3, n=3), daily(probe_check))
    combined = combine([voice, motion], NOW)
    assert combined.corroborated is False
    assert combined.status == combined.verdict_status == "provisional"


@pytest.mark.parametrize("hours,corroborated", [(24, True), (24.001, False), (-0.001, False)])
def test_corroboration_window_is_24_hours_before_the_check(probe, hours, corroborated):
    voice = result(speech(dz=3.5), daily(speech))
    motion = result(probe_check(hours, dz=3.5), daily(probe_check))
    combined = combine([voice, motion], NOW)
    assert combined.corroborated is corroborated
    assert ("probe" in combined.current) is corroborated
    # A stale or future modality is still reported, but marked not current.
    assert combined_payload(combined)["modalities"]["probe"]["current"] is corroborated


def test_strongest_modality_sets_overall_status(probe):
    quiet = result(speech(n=3), daily(speech))
    confirmed = result(probe_check(1, dz=3.5),
                       daily(probe_check) + [probe_check(4, dz=3.5)])
    assert confirmed.assessment.status == "change"
    combined = combine([quiet, confirmed], NOW)
    assert combined.status == combined.verdict_status == "change"
    assert combined.fused == confirmed.assessment.fused
    assert combined.corroborated is False


def test_an_enrolling_modality_is_unknown_not_normal(probe):
    quiet = result(speech(n=3), daily(speech))
    enrolling = result(probe_check(1), daily(probe_check, 2))
    assert enrolling.assessment.status == "enrolling"
    assert combine([quiet, enrolling], NOW).status == "enrolling"
    assert combine([], NOW).status == "enrolling"


def test_unregistered_or_duplicate_modalities_are_refused(probe):
    voice = result(speech(), daily(speech))
    with pytest.raises(ValueError):
        combine([voice, voice], NOW)
    with pytest.raises(ValueError):
        combine([ModalityResult("unknown", NOW, voice.assessment)], NOW)


def test_registered_but_missing_modality_is_explicitly_unavailable(probe):
    combined = combine([result(speech(n=3), daily(speech))], NOW)
    payload = combined_payload(combined)
    assert payload["modalities"]["probe"]["status"] == "unavailable"
    assert payload["modalities"]["probe"]["ts"] is None
    assert payload["modalities"]["probe"]["per_feature"] == {}
    assert payload["modalities"]["probe"]["current"] is False
    assert not payload["corroborated"]
