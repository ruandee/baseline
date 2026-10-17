from datetime import timedelta
from uuid import uuid4

import jwt
import pytest
from pydantic import ValidationError

from patient_memory.auth import Identity, decode_token, synthetic_token
from patient_memory.config import Settings
from patient_memory.domain import Question, Record, SourceInput, Summary, now
from patient_memory.errors import Problem


def test_identity_rejects_wrong_signer():
    identity = Identity(uuid4(), uuid4())
    cfg = Settings()
    assert decode_token(synthetic_token(identity, cfg), cfg) == identity
    with pytest.raises(Problem):
        decode_token(synthetic_token(identity, cfg), Settings(jwt_secret="different" * 8))


@pytest.mark.parametrize("ttl", [1, 7, 48, 72])
def test_synthetic_token_uses_configured_ttl(ttl, monkeypatch):
    identity = Identity(uuid4(), uuid4())
    monkeypatch.setenv("PM_TOKEN_TTL_HOURS", str(ttl))
    cfg = Settings()
    token = synthetic_token(identity, cfg)
    decoded = jwt.decode(token, cfg.jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
    assert decoded["exp"] - decoded["iat"] == ttl * 60 * 60


def test_expired_synthetic_token_is_rejected(monkeypatch):
    issued = now() - timedelta(hours=2)
    monkeypatch.setattr("patient_memory.auth.now", lambda: issued)
    cfg = Settings(token_ttl_hours=1)
    token = synthetic_token(Identity(uuid4(), uuid4()), cfg)
    with pytest.raises(Problem) as error:
        decode_token(token, cfg)
    assert error.value.status == 401


def test_invalid_contracts():
    with pytest.raises(ValidationError):
        Question(question="q", known_at=now() + timedelta(days=1))
    with pytest.raises(ValidationError):
        Record(concept="drug", value="x", event_type="stopped")
    with pytest.raises(ValidationError):
        Record(concept="synthetic-observation", value=float("nan"))
    with pytest.raises(ValidationError):
        Summary(shift_start=now(), shift_end=now() - timedelta(hours=1))
    with pytest.raises(ValidationError):
        SourceInput(external_document_id="x", external_version_id="x", source_system="test",
                    kind="nursing_note", author_role="patient", recorded_at=now(), text="x")
