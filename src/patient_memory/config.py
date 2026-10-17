from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env", extra="ignore")
    environment: str = "synthetic"
    database_url: str = "postgresql://pm_runtime:synthetic-runtime@localhost:55432/patient_memory"
    admin_database_url: str = "postgresql://postgres:synthetic-admin@localhost:55432/patient_memory"
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

    @model_validator(mode="after")
    def safe_mode(self):
        if self.environment != "synthetic":
            raise ValueError("Only synthetic mode is supported until pilot decisions are approved")
        if self.provider not in {"stub", "compatible"}:
            raise ValueError("Unknown model provider")
        return self


def settings() -> Settings:
    return Settings()
