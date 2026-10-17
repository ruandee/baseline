import pytest
from pydantic import ValidationError

from patient_memory.config import Settings


def test_production_cannot_use_synthetic_identity():
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_offline_default():
    assert Settings().provider == "stub"
