import pytest
from pydantic import ValidationError

from patient_memory.config import Settings


def test_production_cannot_use_synthetic_identity():
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_offline_default():
    assert Settings().provider == "stub"

@pytest.mark.parametrize("ttl", [0, -1])
def test_token_ttl_must_be_positive(ttl):
    with pytest.raises(ValidationError):
        Settings(token_ttl_hours=ttl)
