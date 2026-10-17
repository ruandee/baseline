from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from patient_memory.auth import Identity, synthetic_token
from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.errors import Problem
from scripts.hosted_demo import deployment_settings, hosted_app
from scripts.seed import uid


def configure(monkeypatch, role="nurse"):
    cfg = Settings(jwt_secret="deployment-only-test-secret-32-characters")
    token = synthetic_token(Identity(uid(f"0/{role}"), uid("tenant-0")), cfg)
    monkeypatch.setenv("PM_FRONTEND_HOSTS", "demo.example.com")
    monkeypatch.setenv("PM_DEMO_TOKEN", token)
    return cfg, token


def test_hosted_startup_requires_explicit_hosts_and_nurse_token(monkeypatch):
    cfg, _ = configure(monkeypatch)
    for hosts in ("", "*", "https://demo.example.com", "demo.example.com:443"):
        monkeypatch.setenv("PM_FRONTEND_HOSTS", hosts)
        with pytest.raises(ValueError):
            hosted_app(cfg)
    cfg, _ = configure(monkeypatch, "admin")
    with pytest.raises(ValueError, match="nurse token"):
        hosted_app(cfg)
    configure(monkeypatch)
    monkeypatch.delenv("PM_DEMO_TOKEN")
    with pytest.raises(ValueError):
        hosted_app(cfg)


def test_expired_token_fails_before_server_starts(monkeypatch):
    cfg, token = configure(monkeypatch)
    claims = jwt.decode(token, cfg.jwt_secret, algorithms=["HS256"],
                        options={"verify_aud": False})
    claims["exp"] = now() - timedelta(seconds=1)
    monkeypatch.setenv("PM_DEMO_TOKEN", jwt.encode(claims, cfg.jwt_secret, algorithm="HS256"))
    with pytest.raises(Problem):
        hosted_app(cfg)


def test_hosted_session_enforces_host_and_https_origin(monkeypatch):
    cfg, token = configure(monkeypatch)
    client = TestClient(hosted_app(cfg), base_url="https://demo.example.com",
                        client=("192.0.2.10", 1234))
    headers = {"X-PM-Demo": "1", "Origin": "https://demo.example.com"}
    response = client.get("/demo/session", headers=headers)
    assert response.status_code == 200
    assert response.json()["token"] == token
    assert response.headers["cache-control"] == "no-store"
    assert len(response.json()["patients"]) == 6
    for overrides in ({"Host": "evil.example.com"}, {"Origin": "https://evil.example.com"},
                      {"Origin": "http://demo.example.com"}, {"Sec-Fetch-Site": "cross-site"}):
        assert client.get("/demo/session", headers=headers | overrides).status_code == 403
    assert client.get("/demo/session").status_code == 403


def test_hosted_settings_reject_default_signing_secret(monkeypatch):
    for secret in (Settings.model_fields["jwt_secret"].default, "short"):
        monkeypatch.setenv("PM_JWT_SECRET", secret)
        with pytest.raises(ValueError, match="deployment-only"):
            deployment_settings()
