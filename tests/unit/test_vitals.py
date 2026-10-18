from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from patient_memory.baseline.engine import evaluate
from patient_memory.baseline.vitals import VITALS, observation_checks, projection
from patient_memory.config import Settings

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def row(value=16.0, *, name="resting_rr_bpm", at=NOW, unit="breaths/min"):
    return {"id": uuid4(), "concept": name, "value": str(value), "unit": unit, "valid_from": at}


def history(name="resting_rr_bpm", value=16.0, unit="breaths/min"):
    return [row(value, name=name, unit=unit, at=NOW-timedelta(days=8-i)) for i in range(6)]


def test_rr_alone_has_explicit_modality_policy_and_confirms_on_repeat():
    rows = history()+[row(26, at=NOW-timedelta(hours=1)), row(26)]
    checks = observation_checks(rows, "synthetic-mrs-k")
    first = evaluate(checks[-2], checks[:-2], "rolling", Settings())
    repeat = evaluate(checks[-1], checks[:-1], "rolling", Settings())
    assert first.status == "provisional" and repeat.status == "change"
    assert repeat.params["min_features"] == repeat.params["cusum_min_features"] == 1
    assert repeat.params["absolute_floors"]["resting_rr_bpm"] == 1.0
    assert repeat.params["directions"]["resting_rr_bpm"] == 1
    assert "resting_hr_bpm" not in repeat.features
    assert checks[-1].features["resting_hr_bpm"] is None


@pytest.mark.parametrize("value", [42, 78])
def test_hr_is_two_sided_with_specified_three_bpm_floor(value):
    rows = history("resting_hr_bpm", 60, "bpm")+[row(value, name="resting_hr_bpm", unit="bpm")]
    checks = observation_checks(rows, "synthetic")
    result = evaluate(checks[-1], checks[:-1], "rolling", Settings())
    assert result.status == "provisional"
    assert result.params["directions"]["resting_hr_bpm"] == 0
    assert result.params["absolute_floors"]["resting_hr_bpm"] == 3.0
    assert VITALS.name == "vitals"


@pytest.mark.parametrize("value,unit", [(16, "bpm"), (float("nan"), "breaths/min"),
                                         (0, "breaths/min"), ("not measured", "breaths/min")])
def test_invalid_rr_is_unknown_never_a_zero_or_normal_reading(value, unit):
    check, = observation_checks([row(value, unit=unit)], "synthetic")
    assert not check.usable and check.features["resting_rr_bpm"] is None
    assert not check.evidence_ids


def test_unknown_time_generic_rr_and_conflicts_are_not_guessed():
    assert observation_checks([row(at=None), row(name="respiratory_rate")], "synthetic") == []
    conflicted, = observation_checks([row(16), row(26)], "synthetic")
    assert not conflicted.usable
    assert observation_checks([row()], "synthetic")[0].id == observation_checks([row(20)], "synthetic")[0].id


class Result:
    def __init__(self, rows): self.rows = rows
    def fetchone(self): return {"safety": False}
    def fetchall(self): return self.rows


class Conn:
    def __init__(self, rows): self.rows = rows
    def execute(self, sql, params=None): return Result(self.rows)


def test_projection_echoes_unvalidated_policy_and_actual_event_time():
    rows = history()+[row(26)]
    result = projection(Conn(rows), Settings(), "synthetic", NOW)
    assert result.ts == NOW and result.modality == "vitals"
    assert result.assessment.params["threshold_status"] == "engineering_unvalidated"
    assert result.assessment.params["unavailable_features"] == ["resting_hr_bpm"]
    assert projection(Conn(rows), Settings(), "synthetic", NOW+timedelta(hours=25)) is None
