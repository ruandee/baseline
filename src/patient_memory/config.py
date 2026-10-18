import re
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

E164 = r"\+[1-9][0-9]{7,14}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env", extra="ignore")
    environment: str = "synthetic"
    database_url: str = "postgresql://pm_runtime:synthetic-runtime@127.0.0.1:55432/patient_memory?connect_timeout=5"
    admin_database_url: str = "postgresql://postgres:synthetic-admin@127.0.0.1:55432/patient_memory?connect_timeout=5"
    jwt_secret: str = "synthetic-local-only-change-before-any-deployment"
    jwt_public_key: str = ""
    jwt_issuer: str = "patient-memory-synthetic"
    jwt_audience: str = "patient-memory-api"
    token_ttl_hours: int = Field(default=48, gt=0)
    object_endpoint: str = "http://localhost:59000"
    object_access_key: str = "synthetic-local"
    object_secret_key: str = "synthetic-local-secret"
    object_bucket: str = "synthetic-sources"
    rate_limit: int = 30
    max_payload_bytes: int = 2 * 1024 * 1024
    max_evidence: int = 12
    provider: str = "stub"
    provider_url: str = ""
    provider_model: str = ""
    provider_key: str = ""
    whisper_model: str = "base"
    keep_audio: bool = False
    z_threshold: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    # Free conversation (Vox encounters) is noisier than the counting prompt.
    z_threshold_free: float = Field(default=2.5, gt=0, allow_inf_nan=False)
    provisional_z: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    min_features: int = Field(default=2, ge=1, le=4)
    ewma_lambda: float = Field(default=0.3, gt=0, le=1, allow_inf_nan=False)
    cusum_k: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    cusum_h: float = Field(default=4.0, gt=0, allow_inf_nan=False)
    escalation_budget: int = Field(default=3, ge=0)
    shift_timezone: str = "America/Toronto"
    # Comma-separated patient UUIDs that never escalate (the demo runner).
    no_escalate_patients: str = ""
    # KAZE escalation texts (decision 023). "log" never sends; "twilio" needs every field below.
    sms_provider: str = "log"
    sms_allowed_recipients: str = ""  # comma-separated E.164 numbers Twilio may text
    twilio_sid: str = ""
    twilio_token: str = Field(default="", repr=False)
    twilio_from: str = ""  # E.164 number or a Messaging Service SID (MG...)
    ack_base_url: str = "http://127.0.0.1:8000"
    ack_ttl_min: int = Field(default=360, ge=5, le=1440)

    @model_validator(mode="after")
    def safe_mode(self):
        if self.environment != "synthetic":
            raise ValueError("Only synthetic mode is supported until pilot decisions are approved")
        self._check_sms()
        if self.provider not in {"stub", "compatible", "ollama"}:
            raise ValueError("Unknown model provider")
        if self.provider in {"compatible", "ollama"}:
            url = urlparse(self.provider_url)
            local = url.hostname in {"127.0.0.1", "localhost", "::1"}
            if (not self.provider_model or not url.hostname or url.username or url.password
                    or url.query or url.fragment or (url.scheme != "https" and not (local and url.scheme == "http"))):
                raise ValueError("Configure a model and HTTPS provider URL (HTTP allowed only for loopback)")
        return self

    def _check_sms(self):
        if self.sms_provider not in {"log", "twilio"}:
            raise ValueError("Unknown SMS provider")
        url = urlparse(self.ack_base_url)
        local = url.hostname in {"127.0.0.1", "localhost", "::1"}
        if (not url.hostname or url.username or url.password or url.query or url.fragment
                or (url.scheme != "https" and not (local and url.scheme == "http"))):
            raise ValueError("PM_ACK_BASE_URL must be HTTPS (HTTP allowed only for loopback)")
        if self.sms_provider == "twilio":
            recipients = [p.strip() for p in self.sms_allowed_recipients.split(",") if p.strip()]
            if (not re.fullmatch(r"AC[0-9a-fA-F]{32}", self.twilio_sid) or not self.twilio_token
                    or not (re.fullmatch(E164, self.twilio_from)
                            or re.fullmatch(r"MG[0-9a-fA-F]{32}", self.twilio_from))):
                raise ValueError("Twilio needs PM_TWILIO_SID, PM_TWILIO_TOKEN and PM_TWILIO_FROM")
            if not recipients or not all(re.fullmatch(E164, p) for p in recipients):
                raise ValueError("Twilio needs PM_SMS_ALLOWED_RECIPIENTS (approved E.164 numbers)")
            if url.scheme != "https":
                raise ValueError("Real texts need an HTTPS PM_ACK_BASE_URL a phone can open")


def settings() -> Settings:
    return Settings()
