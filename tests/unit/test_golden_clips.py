import shutil
from pathlib import Path

import pytest

from patient_memory.speech.pipeline import analyze

# Real recordings of the fixed prompt; kept out of Git (data/raw/ is ignored). See docs/operations.md.
GOLDEN = Path(__file__).parents[2] / "data" / "raw" / "golden"
STEMS = ("normal", "slow", "pausey", "stairs")


def takes(stem):
    return sorted(GOLDEN.glob(stem + ".*"))


missing = [stem for stem in STEMS if not takes(stem)]
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed"),
    pytest.mark.skipif(bool(missing), reason=f"record {', '.join(missing)} into {GOLDEN}"),
]

# One scale unit of the change engine (docs/06-baseline.md, "Per-feature score"): the larger of 5%
# of the baseline value and the feature's abs_floor. A single take has no MAD to add, and the engine
# only flags at 2 units, so asking for 1 is the least a real change should show.
ABS_FLOOR = {"speech_rate_wpm": 5.0, "pause_ratio": 0.02, "f0_median_hz": 5.0}


@pytest.fixture(scope="module")
def checks(tmp_path_factory):
    """Each clip through the production pipeline with real Whisper, once."""
    stale = {stem: [p.name for p in takes(stem)] for stem in STEMS if len(takes(stem)) > 1}
    if stale:  # a stale take would silently win otherwise
        pytest.fail(f"keep one recording per stem, found {stale}")
    work = tmp_path_factory.mktemp("golden")
    results = {}
    for stem in STEMS:
        scratch = work / stem
        scratch.mkdir()
        results[stem] = analyze(takes(stem)[0], scratch)
    return results


def measured(checks, *stems):
    return "; ".join(
        f"{stem}: {checks[stem].features}, {len(checks[stem].pauses)} pauses, "
        f"{len(checks[stem].words)} words, quality {checks[stem].quality}" for stem in stems)


def feature(checks, stem, name):
    value = checks[stem].features[name]
    assert value is not None, f"{name} is undefined for {stem}: {measured(checks, stem)}"
    return value


def margin(checks, name):
    return max(0.05 * abs(feature(checks, "normal", name)), ABS_FLOOR[name])


def test_every_golden_clip_passes_the_quality_gate(checks):
    failed = {stem: check.quality["reasons"] for stem, check in checks.items() if not check.usable}
    assert not failed, f"{failed}\n{measured(checks, *failed)}"


def test_slow_clip_lowers_speech_rate(checks):
    normal, slow = (feature(checks, stem, "speech_rate_wpm") for stem in ("normal", "slow"))
    assert slow < normal - margin(checks, "speech_rate_wpm"), measured(checks, "normal", "slow")


def test_pausey_clip_raises_pause_ratio(checks):
    normal, pausey = (feature(checks, stem, "pause_ratio") for stem in ("normal", "pausey"))
    assert pausey > normal + margin(checks, "pause_ratio"), measured(checks, "normal", "pausey")
    assert len(checks["pausey"].pauses) > len(checks["normal"].pauses), (
        measured(checks, "normal", "pausey"))


def test_stairs_clip_raises_pitch(checks):
    normal, stairs = (feature(checks, stem, "f0_median_hz") for stem in ("normal", "stairs"))
    assert stairs > normal + margin(checks, "f0_median_hz"), measured(checks, "normal", "stairs")
