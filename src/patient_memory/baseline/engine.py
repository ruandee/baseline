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
POLICY_VERSION = "multifeature-cusum-v2"
CUSUM_MIN_FEATURES = 2

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
        "policy_version": POLICY_VERSION,
        "cusum_min_features": CUSUM_MIN_FEATURES,
        "cusum_confirmation_hours": CONSECUTIVE_WITHIN.total_seconds() / 3600,
        "cusum_requires_ongoing_deviation": True,
        "pitch_cusum": "separate_signed_streams",
        "instantaneous_requires_same_features": True,
        "instantaneous_requires_same_pitch_direction": True,
    }
    if len(baseline) < MIN_BASELINE:
        return Assessment("enrolling", {}, None, (), params)
    sequence = _prefer_device(check, usable)[-(SEQUENCE - 1):] + [check]
    scores, previous_dz, previous_direction = {}, {}, {}
    supported, previous_supported = {}, {}
    for name in FEATURES:
        values = [c.features[name] for c in baseline if c.features.get(name) is not None]
        if len(values) < MIN_BASELINE:
            continue
        m = median(values)
        scale = max(MAD_SCALE * median(abs(v - m) for v in values), REL_FLOOR * abs(m),
                    FEATURES[name][1])
        ewma = cusum = negative_cusum = 0.0
        for c in sequence:
            value = c.features.get(name)
            if value is None:
                continue
            z, dz = _dz(name, value, m, scale)
            ewma = cfg.ewma_lambda * dz + (1 - cfg.ewma_lambda) * ewma
            if FEATURES[name][0] == 0:
                # Pooling abs(z) into one stream accumulates alternating pitch noise.
                cusum = max(0.0, cusum + z - cfg.cusum_k)
                negative_cusum = max(0.0, negative_cusum - z - cfg.cusum_k)
                ongoing = ((cusum >= cfg.cusum_h and z > cfg.cusum_k)
                           or (negative_cusum >= cfg.cusum_h and -z > cfg.cusum_k))
                direction = 1 if z > 0 else -1
            else:
                cusum = max(0.0, cusum + dz - cfg.cusum_k)
                ongoing = cusum >= cfg.cusum_h and dz > cfg.cusum_k
                direction = 1
            if c is check:
                scores[name] = FeatureScore(value, m, scale, z, dz, ewma,
                                            max(cusum, negative_cusum))
                if ongoing:
                    supported[name] = direction
            elif c.ts >= check.ts - CONSECUTIVE_WITHIN and c is sequence[-2]:
                previous_dz[name] = dz
                previous_direction[name] = direction
                if ongoing:
                    previous_supported[name] = direction
    if not scores:  # no feature has enough baseline values: still enrolling, not a negative
        return Assessment("enrolling", {}, None, tuple(c.id for c in baseline), params)
    dzs = [s.dz for s in scores.values()]
    fused = mean(dzs)
    # Accumulated values remain visible as diagnostics after recovery, but cannot alone
    # maintain a status. Confirm the same supported features and pitch direction twice.
    alarm = len(supported) >= CUSUM_MIN_FEATURES
    sustained = sum(previous_supported.get(name) == direction
                    for name, direction in supported.items()) >= CUSUM_MIN_FEATURES
    confirmed = sum(
        s.dz > cfg.z_threshold and previous_dz.get(name, float("-inf")) > cfg.z_threshold
        and (FEATURES[name][0] != 0 or previous_direction.get(name) == (1 if s.z > 0 else -1))
        for name, s in scores.items()) >= cfg.min_features
    if sustained or confirmed:
        status = "change"
    elif alarm or _over(cfg.provisional_z, dzs, cfg.min_features):
        status = "provisional"
    else:
        status = "none"
    return Assessment(status, scores, fused, tuple(c.id for c in baseline), params)
