from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from statistics import mean, median
from typing import Literal

from patient_memory.config import Settings

Mode = Literal["rolling", "enrolled"]
Status = Literal["enrolling", "none", "provisional", "change"]

MIN_BASELINE = 3
ROLLING_CHECKS = 10
ROLLING_WINDOW = timedelta(days=30)
ROLLING_GUARD = timedelta(hours=12)
SEQUENCE = 20
CONSECUTIVE_WITHIN = timedelta(hours=24)
CORROBORATION_WINDOW = timedelta(hours=24)
MAD_SCALE = 1.4826
REL_FLOOR = 0.05
POLICY_VERSION = "multifeature-cusum-v2"
CUSUM_MIN_FEATURES = 2


@dataclass(frozen=True)
class FeatureSpec:
    """One declared feature. direction: -1 lower is concerning, +1 higher, 0 two-sided."""
    name: str
    modality: str
    direction: Literal[-1, 0, 1]
    abs_floor: float
    label: str | None = None
    unit: str | None = None

    def __post_init__(self):
        if self.direction not in (-1, 0, 1):
            raise ValueError(f"invalid direction for {self.name}")
        if not isfinite(self.abs_floor) or not self.abs_floor > 0:
            raise ValueError(f"absolute floor must be positive for {self.name}")


@dataclass(frozen=True)
class Modality:
    """A signal modality: its features and any per-modality confirmation counts.

    `min_features=None` means `Settings.min_features`. Per-modality overrides are a policy
    decision (decision 025) and are echoed in every result's params.
    """
    name: str
    features: tuple[FeatureSpec, ...]
    min_features: int | None = None
    cusum_min_features: int = CUSUM_MIN_FEATURES

    def __post_init__(self):
        if not self.features:
            raise ValueError(f"modality {self.name} declares no features")
        names = [f.name for f in self.features]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate feature in modality {self.name}")
        if any(f.modality != self.name for f in self.features):
            raise ValueError(f"feature declared under the wrong modality in {self.name}")
        for count in (self.min_features, self.cusum_min_features):
            if count is not None and not 1 <= count <= len(self.features):
                raise ValueError(f"feature count out of range for modality {self.name}")


SPEECH = Modality("speech", (
    FeatureSpec("speech_rate_wpm", "speech", -1, 5.0),
    FeatureSpec("pause_ratio", "speech", 1, 0.02),
    FeatureSpec("mean_pause_s", "speech", 1, 0.05),
    FeatureSpec("f0_median_hz", "speech", 0, 5.0),
))
REGISTRY: dict[str, Modality] = {}


def register(modality: Modality) -> Modality:
    """Declare a modality. Names are unique, and a feature belongs to one modality only, so
    histories and baselines of different modalities can never mix."""
    if modality.name in REGISTRY:
        raise ValueError(f"modality {modality.name} is already registered")
    taken = {f.name for m in REGISTRY.values() for f in m.features}
    if taken & {f.name for f in modality.features}:
        raise ValueError(f"feature names of {modality.name} are already registered")
    REGISTRY[modality.name] = modality
    return modality


register(SPEECH)

# Speech features as name -> (direction, absolute floor); voice_checks columns use this.
FEATURES = {f.name: (f.direction, f.abs_floor) for f in SPEECH.features}


@dataclass(frozen=True)
class Check:
    id: str
    ts: datetime
    device_id: str
    prompt_version: str
    is_baseline: bool
    usable: bool
    features: dict[str, float | None]
    modality: str = "speech"
    evidence_ids: tuple[str, ...] = ()


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
    status: Status
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


def _dz(spec: FeatureSpec, value: float, m: float, scale: float) -> tuple[float, float]:
    z = (value - m) / scale
    return z, abs(z) if spec.direction == 0 else spec.direction * z


def _over(limit: float, dzs: Iterable[float], min_features: int) -> bool:
    return sum(dz > limit for dz in dzs) >= min_features


def evaluate(check: Check, history: Sequence[Check], mode: Mode, cfg: Settings) -> Assessment:
    """Score `check` against the patient's usable history; stateless, nothing is stored.

    Only the features declared for the check's modality are scored, and history of any other
    modality is ignored. Unusable checks never reach the engine, so passing one is an error.
    """
    if not check.usable:
        raise ValueError("unusable checks are not scored")
    modality = check.modality
    spec = REGISTRY[modality]
    specs = spec.features
    min_features = spec.min_features or cfg.min_features
    usable = sorted((c for c in history
                     if c.usable and c.id != check.id and c.ts < check.ts
                     and c.modality == modality
                     and c.prompt_version == check.prompt_version), key=lambda c: c.ts)
    baseline = _baseline(check, usable, mode)
    params = {
        "modality": modality,
        "mode": mode, "baseline_checks": len(baseline), "z_threshold": cfg.z_threshold,
        "provisional_z": cfg.provisional_z, "min_features": min_features,
        "ewma_lambda": cfg.ewma_lambda, "cusum_k": cfg.cusum_k, "cusum_h": cfg.cusum_h,
        "mad_scale": MAD_SCALE, "relative_floor": REL_FLOOR, "min_baseline": MIN_BASELINE,
        "directions": {f.name: f.direction for f in specs},
        "absolute_floors": {f.name: f.abs_floor for f in specs},
        "rolling_checks": ROLLING_CHECKS, "rolling_window_days": ROLLING_WINDOW.days,
        "rolling_guard_hours": ROLLING_GUARD.total_seconds() / 3600,
        "sequence_checks": SEQUENCE,
        "consecutive_hours": CONSECUTIVE_WITHIN.total_seconds() / 3600,
        "policy_version": POLICY_VERSION,
        "cusum_min_features": spec.cusum_min_features,
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
    two_sided = {f.name for f in specs if f.direction == 0}
    for feature in specs:
        name = feature.name
        values = [c.features[name] for c in baseline if c.features.get(name) is not None]
        if len(values) < MIN_BASELINE:
            continue
        m = median(values)
        scale = max(MAD_SCALE * median(abs(v - m) for v in values), REL_FLOOR * abs(m),
                    feature.abs_floor)
        ewma = cusum = negative_cusum = 0.0
        for c in sequence:
            value = c.features.get(name)
            if value is None:
                continue
            z, dz = _dz(feature, value, m, scale)
            ewma = cfg.ewma_lambda * dz + (1 - cfg.ewma_lambda) * ewma
            if feature.direction == 0:
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
    alarm = len(supported) >= spec.cusum_min_features
    sustained = sum(previous_supported.get(name) == direction
                    for name, direction in supported.items()) >= spec.cusum_min_features
    confirmed = sum(
        s.dz > cfg.z_threshold and previous_dz.get(name, float("-inf")) > cfg.z_threshold
        and (name not in two_sided or previous_direction.get(name) == (1 if s.z > 0 else -1))
        for name, s in scores.items()) >= min_features
    if sustained or confirmed:
        status = "change"
    elif alarm or _over(cfg.provisional_z, dzs, min_features):
        status = "provisional"
    else:
        status = "none"
    return Assessment(status, scores, fused, tuple(c.id for c in baseline), params)


# `enrolling` outranks `none`: within_normal is claimed only when every current modality has
# a baseline. An incomplete modality is reported as incomplete, not as a negative finding.
STATUS_RANK = {"none": 0, "enrolling": 1, "provisional": 2, "change": 3}
FLAGGED = ("provisional", "change")


@dataclass(frozen=True)
class ModalityResult:
    """One modality's assessment of its own latest check at `ts`."""
    modality: str
    ts: datetime
    assessment: Assessment
    check_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Combined:
    """Registry-level result. `status` is the strongest current modality status;
    `verdict_status` is what the verdict table receives (a corroborated provisional is change).
    `current` lists the modalities whose result is inside the corroboration window."""
    status: Status
    verdict_status: Status
    corroborated: bool
    fused: float | None
    modalities: dict[str, ModalityResult]
    current: tuple[str, ...]


def combine(results: Iterable[ModalityResult], at: datetime) -> Combined:
    """Combine per-modality results as of `at` (the triggering check's time).

    A result counts only if its check is at most 24 h before `at` and not after it, so a stale
    reading cannot raise or corroborate today's status. A modality with no current result is
    unknown, never `none`. Overall status is the strongest current status (change, then
    provisional, then enrolling, then none); with no current result at all it is `enrolling`.
    `corroborated` is true when 2 or more current modalities are provisional or change.
    """
    by_modality: dict[str, ModalityResult] = {}
    for result in results:
        if result.modality not in REGISTRY:
            raise ValueError(f"unregistered modality: {result.modality}")
        if result.modality in by_modality:
            raise ValueError(f"duplicate result for modality {result.modality}")
        by_modality[result.modality] = result
    current = [r for r in by_modality.values() if at - CORROBORATION_WINDOW <= r.ts <= at]
    if not current:
        return Combined("enrolling", "enrolling", False, None, by_modality, ())
    strongest = max(STATUS_RANK[r.assessment.status] for r in current)
    top = [r for r in current if STATUS_RANK[r.assessment.status] == strongest]
    status = top[0].assessment.status
    fused_values = [r.assessment.fused for r in top if r.assessment.fused is not None]
    fused = max(fused_values) if fused_values else None
    corroborated = sum(r.assessment.status in FLAGGED for r in current) >= 2
    verdict_status = "change" if corroborated and status == "provisional" else status
    return Combined(status, verdict_status, corroborated, fused, by_modality,
                    tuple(sorted(r.modality for r in current)))


def combined_payload(combined: Combined) -> dict:
    """JSON-ready per-modality results; stale modalities are listed with current=false."""
    return {
        "status": combined.status, "verdict_status": combined.verdict_status,
        "corroborated": combined.corroborated, "fused_z": combined.fused,
        "corroboration_hours": CORROBORATION_WINDOW.total_seconds() / 3600,
        "modalities": {
            name: {"status": r.assessment.status, "ts": r.ts.isoformat(),
                   "check_id": r.check_id, "evidence_ids": list(r.evidence_ids),
                   "current": name in combined.current, "fused_z": r.assessment.fused,
                   "params": r.assessment.params,
                   "baseline_checks": r.assessment.params.get("baseline_checks"),
                   "per_feature": {f: {"value": v.value, "median": v.median, "scale": v.scale,
                                       "z": v.z, "ewma": v.ewma, "cusum": v.cusum}
                                   for f, v in r.assessment.features.items()}}
            for name, r in sorted(combined.modalities.items())} | {
                name: {"status": "unavailable", "ts": None, "check_id": None,
                       "evidence_ids": [], "current": False, "fused_z": None,
                       "params": {}, "baseline_checks": None, "per_feature": {}}
                for name in sorted(REGISTRY) if name not in combined.modalities},
    }
