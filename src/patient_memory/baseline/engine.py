from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Literal

from patient_memory.config import Settings

Mode = Literal["rolling", "enrolled"]

MIN_BASELINE = 3
ROLLING_CHECKS = 10
ROLLING_WINDOW = timedelta(days=30)
ROLLING_GUARD = timedelta(hours=12)
SEQUENCE = 20
CONSECUTIVE_WITHIN = timedelta(hours=24)
MAD_SCALE = 1.4826
REL_FLOOR = 0.05

# direction: -1 slower is concerning, +1 higher is concerning, 0 two-sided.
FEATURES = {
    "speech_rate_wpm": (-1, 5.0),
    "pause_ratio": (1, 0.02),
    "mean_pause_s": (1, 0.05),
    "f0_median_hz": (0, 5.0),
}


@dataclass(frozen=True)
class Check:
    id: str
    ts: datetime
    device_id: str
    prompt_version: str
    is_baseline: bool
    usable: bool
    features: dict[str, float | None]


@dataclass(frozen=True)
class FeatureScore:
    value: float
    median: float
    scale: float
    z: float
    dz: float
    ewma: float
    cusum: float


@dataclass(frozen=True)
class Assessment:
    status: Literal["enrolling", "none", "provisional", "change"]
    features: dict[str, FeatureScore]
    fused: float | None
    baseline_ids: tuple[str, ...]
    params: dict


def _prefer_device(check: Check, pool: list[Check]) -> list[Check]:
    same_device = [c for c in pool if c.device_id == check.device_id]
    return same_device if len(same_device) >= MIN_BASELINE else pool


def _baseline(check: Check, history: list[Check], mode: Mode) -> list[Check]:
    if mode == "enrolled":
        return _prefer_device(check, [c for c in history if c.is_baseline])
    window = [c for c in history if check.ts - ROLLING_WINDOW <= c.ts <= check.ts - ROLLING_GUARD]
    return _prefer_device(check, window)[-ROLLING_CHECKS:]


def _dz(name: str, value: float, m: float, scale: float) -> tuple[float, float]:
    z = (value - m) / scale
    return z, abs(z) if FEATURES[name][0] == 0 else FEATURES[name][0] * z


def _over(limit: float, dzs: Iterable[float], min_features: int) -> bool:
    return sum(dz > limit for dz in dzs) >= min_features


def evaluate(check: Check, history: Sequence[Check], mode: Mode, cfg: Settings) -> Assessment:
    """Score `check` against the patient's usable history; stateless, nothing is stored.

    Unusable checks never reach the engine, so passing one is an error rather than a score.
    """
    if not check.usable:
        raise ValueError("unusable checks are not scored")
    usable = sorted((c for c in history
                     if c.usable and c.id != check.id and c.ts < check.ts
                     and c.prompt_version == check.prompt_version), key=lambda c: c.ts)
    baseline = _baseline(check, usable, mode)
    params = {
        "mode": mode, "baseline_checks": len(baseline), "z_threshold": cfg.z_threshold,
        "provisional_z": cfg.provisional_z, "min_features": cfg.min_features,
        "ewma_lambda": cfg.ewma_lambda, "cusum_k": cfg.cusum_k, "cusum_h": cfg.cusum_h,
        "mad_scale": MAD_SCALE, "relative_floor": REL_FLOOR, "min_baseline": MIN_BASELINE,
        "directions": {n: d for n, (d, _) in FEATURES.items()},
        "absolute_floors": {n: f for n, (_, f) in FEATURES.items()},
        "rolling_checks": ROLLING_CHECKS, "rolling_window_days": ROLLING_WINDOW.days,
        "rolling_guard_hours": ROLLING_GUARD.total_seconds() / 3600,
        "sequence_checks": SEQUENCE,
        "consecutive_hours": CONSECUTIVE_WITHIN.total_seconds() / 3600,
    }
    if len(baseline) < MIN_BASELINE:
        return Assessment("enrolling", {}, None, (), params)
    sequence = _prefer_device(check, usable)[-(SEQUENCE - 1):] + [check]
    scores, previous_dz = {}, {}
    for name in FEATURES:
        values = [c.features[name] for c in baseline if c.features.get(name) is not None]
        if len(values) < MIN_BASELINE:
            continue
        m = median(values)
        scale = max(MAD_SCALE * median(abs(v - m) for v in values), REL_FLOOR * abs(m),
                    FEATURES[name][1])
        ewma = cusum = 0.0
        for c in sequence:
            value = c.features.get(name)
            if value is None:
                continue
            z, dz = _dz(name, value, m, scale)
            ewma = cfg.ewma_lambda * dz + (1 - cfg.ewma_lambda) * ewma
            cusum = max(0.0, cusum + dz - cfg.cusum_k)
            if c is check:
                scores[name] = FeatureScore(value, m, scale, z, dz, ewma, cusum)
            elif c.ts >= check.ts - CONSECUTIVE_WITHIN and c is sequence[-2]:
                previous_dz[name] = dz
    if not scores:  # no feature has enough baseline values: still enrolling, not a negative
        return Assessment("enrolling", {}, None, tuple(c.id for c in baseline), params)
    dzs = [s.dz for s in scores.values()]
    fused = mean(dzs)
    alarm = any(s.cusum >= cfg.cusum_h for s in scores.values())
    confirmed = (_over(cfg.z_threshold, dzs, cfg.min_features)
                 and _over(cfg.z_threshold, previous_dz.values(), cfg.min_features))
    if alarm or confirmed:
        status = "change"
    elif _over(cfg.provisional_z, dzs, cfg.min_features):
        status = "provisional"
    else:
        status = "none"
    return Assessment(status, scores, fused, tuple(c.id for c in baseline), params)
