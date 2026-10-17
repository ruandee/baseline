from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import jwt

from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.errors import Problem


@dataclass(frozen=True)
class Identity:
    principal_id: UUID
    tenant_id: UUID


def decode_token(token: str, cfg: Settings) -> Identity:
    try:
        data = jwt.decode(
            token, cfg.jwt_secret, algorithms=["HS256"], audience=cfg.jwt_audience,
            issuer=cfg.jwt_issuer, options={"require": ["sub", "tenant", "exp", "iat"]},
        )
        return Identity(UUID(data["sub"]), UUID(data["tenant"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise Problem(401, "invalid_identity", "Valid bearer identity required") from exc


def synthetic_token(identity: Identity, cfg: Settings) -> str:
    return jwt.encode(
        {"sub": str(identity.principal_id), "tenant": str(identity.tenant_id),
         "iss": cfg.jwt_issuer, "aud": cfg.jwt_audience, "iat": now(),
         "exp": now() + timedelta(hours=8)}, cfg.jwt_secret, algorithm="HS256",
    )
