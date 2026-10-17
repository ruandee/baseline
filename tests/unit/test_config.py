import pytest
from pydantic import ValidationError

from patient_memory.config import Settings


def test_production_cannot_use_synthetic_identity():
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_offline_default():
    assert Settings().provider == "stub"


@pytest.mark.parametrize("field", ["z_threshold", "provisional_z", "ewma_lambda", "cusum_h"])
@pytest.mark.parametrize("value", [0, -1, float("inf"), float("-inf"), float("nan")])
def test_engine_positive_parameters_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.mark.parametrize("value", [-1, float("inf"), float("-inf"), float("nan")])
def test_cusum_allowance_rejects_negative_or_nonfinite_values(value):
    with pytest.raises(ValidationError):
        Settings(cusum_k=value)


@pytest.mark.parametrize("value", [0, 5, 1.5])
def test_engine_feature_count_cannot_exceed_available_features(value):
    with pytest.raises(ValidationError):
        Settings(min_features=value)


def test_ewma_cannot_assign_a_negative_weight_to_previous_checks():
    with pytest.raises(ValidationError):
        Settings(ewma_lambda=1.01)


def test_engine_configuration_accepts_boundary_values_from_environment(monkeypatch):
    monkeypatch.setenv("PM_MIN_FEATURES", "4")
    monkeypatch.setenv("PM_EWMA_LAMBDA", "1")
    monkeypatch.setenv("PM_CUSUM_K", "0")
    cfg = Settings()
    assert cfg.min_features == 4
    assert cfg.ewma_lambda == 1
    assert cfg.cusum_k == 0


def test_invalid_engine_environment_configuration_fails_at_startup(monkeypatch):
    monkeypatch.setenv("PM_CUSUM_H", "NaN")
    with pytest.raises(ValidationError):
        Settings()
