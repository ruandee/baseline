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


def test_synthetic_token_uses_configured_ttl():
    identity = Identity(uuid4(), uuid4())
    cfg = Settings(token_ttl_hours=48)
    token = synthetic_token(identity, cfg)
    decoded = jwt.decode(token, cfg.jwt_secret, algorithms=["HS256"], options={"verify_aud": False})
    assert decoded["exp"] - decoded["iat"] == 48 * 60 * 60


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
