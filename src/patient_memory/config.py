from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env", extra="ignore")
    environment: str = "synthetic"
    database_url: str = "postgresql://pm_runtime:synthetic-runtime@127.0.0.1:55432/patient_memory?connect_timeout=5"
    admin_database_url: str = "postgresql://postgres:synthetic-admin@127.0.0.1:55432/patient_memory?connect_timeout=5"
    jwt_secret: str = "synthetic-local-only-change-before-any-deployment"
    jwt_public_key: str = ""
    jwt_issuer: str = "patient-memory-synthetic"
    jwt_audience: str = "patient-memory-api"
    object_endpoint: str = "http://localhost:59000"
    object_access_key: str = "synthetic-local"
    object_secret_key: str = "synthetic-local-secret"
    object_bucket: str = "synthetic-sources"
    rate_limit: int = 30
    max_payload_bytes: int = 2 * 1024 * 1024
    max_evidence: int = 12
    provider: str = "stub"
    provider_url: str = ""
    provider_key: str = ""
    provider_model: str = ""
    whisper_model: str = "base"
    keep_audio: bool = False
    z_threshold: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    provisional_z: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    min_features: int = Field(default=2, ge=1, le=4)
    ewma_lambda: float = Field(default=0.3, gt=0, le=1, allow_inf_nan=False)
    cusum_k: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    cusum_h: float = Field(default=4.0, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def safe_mode(self):
        if self.environment != "synthetic":
            raise ValueError("Only synthetic mode is supported until pilot decisions are approved")
        if self.provider not in {"stub", "compatible", "ollama"}:
            raise ValueError("Unknown model provider")
        if self.provider in {"compatible", "ollama"}:
            url = urlparse(self.provider_url)
            local = url.hostname in {"127.0.0.1", "localhost", "::1"}
            if (not self.provider_model or not url.hostname or url.username or url.password
                    or url.query or url.fragment or (url.scheme != "https" and not (local and url.scheme == "http"))):
                raise ValueError("Configure a model and HTTPS provider URL (HTTP allowed only for loopback)")
        return self


def settings() -> Settings:
    return Settings()
