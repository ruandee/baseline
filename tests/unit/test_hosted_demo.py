from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from patient_memory.auth import Identity, synthetic_token
from patient_memory.config import Settings
from patient_memory.domain import now
from patient_memory.errors import Problem
from scripts.hosted_demo import deployment_settings, hosted_app, runtime_only
from scripts.seed import uid

ROSTER = [{"id": str(uid(f"0/patient-{i}")), "name": f"synthetic-patient-{i}",
           "reference": f"synthetic-patient-{i}", "questions": []} for i in range(6)]


def app_for(cfg):
    return hosted_app(cfg, ROSTER)


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
            app_for(cfg)
    cfg, _ = configure(monkeypatch, "admin")
    with pytest.raises(ValueError, match="nurse token"):
        app_for(cfg)
    configure(monkeypatch)
    monkeypatch.delenv("PM_DEMO_TOKEN")
    with pytest.raises(ValueError):
        app_for(cfg)


def test_expired_token_fails_before_server_starts(monkeypatch):
    cfg, token = configure(monkeypatch)
    claims = jwt.decode(token, cfg.jwt_secret, algorithms=["HS256"],
                        options={"verify_aud": False})
    claims["exp"] = now() - timedelta(seconds=1)
    monkeypatch.setenv("PM_DEMO_TOKEN", jwt.encode(claims, cfg.jwt_secret, algorithm="HS256"))
    with pytest.raises(Problem):
        app_for(cfg)


def test_hosted_session_enforces_host_and_https_origin(monkeypatch):
    cfg, token = configure(monkeypatch)
    client = TestClient(app_for(cfg), base_url="https://demo.example.com",
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


def test_serve_and_worker_refuse_admin_database_url():
    cfg = Settings(jwt_secret="deployment-only-test-secret-32-characters")
    assert cfg.admin_database_url
    with pytest.raises(ValueError, match="admin credentials"):
        runtime_only(cfg)
    blank = Settings(jwt_secret="deployment-only-test-secret-32-characters", admin_database_url="")
    assert runtime_only(blank) is blank


def test_serve_warns_when_demo_token_expires_within_a_day(monkeypatch, caplog):
    for ttl, warned in ((1, True), (48, False)):
        cfg = Settings(jwt_secret="deployment-only-test-secret-32-characters", token_ttl_hours=ttl)
        token = synthetic_token(Identity(uid("0/nurse"), uid("tenant-0")), cfg)
        monkeypatch.setenv("PM_FRONTEND_HOSTS", "demo.example.com")
        monkeypatch.setenv("PM_DEMO_TOKEN", token)
        caplog.clear()
        with caplog.at_level("WARNING", logger="patient_memory.hosted_demo"):
            app_for(cfg)
        assert ("expires in" in caplog.text) is warned


def test_frontend_hosted_mode_refuses_default_secret_before_fixture_writes(monkeypatch):
    import scripts.frontend as frontend

    def no_writes(cfg):
        raise AssertionError("prepare_demo must not run with the public default secret")

    monkeypatch.setattr(frontend, "prepare_demo", no_writes)
    monkeypatch.setenv("PM_FRONTEND_HOSTS", "demo.example.com")
    monkeypatch.setenv("PM_JWT_SECRET", frontend.LOCAL_JWT_SECRET)
    with pytest.raises(ValueError, match="deployment-only"):
        frontend.main()
