import json

import httpx
import pytest

from patient_memory.config import Settings
from scripts.gemini_smoke import list_models, main, smoke


def config(**overrides):
    return Settings(**{
        "provider": "compatible",
        "provider_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "provider_model": "synthetic-model",
        "provider_key": "synthetic-secret",
        **overrides,
    })


def response(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def test_smoke_uses_documented_endpoint_schema_and_no_redirects(monkeypatch):
    def post(endpoint, **kwargs):
        assert endpoint == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        assert kwargs["headers"] == {"Authorization": "Bearer synthetic-secret"}
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        assert kwargs["json"]["response_format"]["json_schema"]["strict"] is True
        assert kwargs["json"]["model"] == "synthetic-model"
        return response({"answer": "Hello", "safe": True})
    monkeypatch.setattr(httpx, "post", post)
    assert smoke(config()).safe is True


@pytest.mark.parametrize("body", [
    {"answer": "Hello", "safe": "true"},
    {"answer": "Hello", "safe": True, "invented": 1},
    {"answer": 42, "safe": True},
    {"answer": "Hello"},
])
def test_smoke_rejects_schema_violations(monkeypatch, body):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response(body))
    with pytest.raises(ValueError, match="failed the smoke schema"):
        smoke(config())


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [None]}, []])
def test_smoke_rejects_invalid_envelopes(monkeypatch, body):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(200, json=body))
    with pytest.raises(ValueError, match="failed the smoke schema"):
        smoke(config())


@pytest.mark.parametrize("status", [400, 401, 404, 429, 500, 307])
def test_provider_errors_have_safe_diagnostics(monkeypatch, status):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(
        status, text="synthetic-secret private provider body"))
    with pytest.raises(ValueError) as error:
        smoke(config())
    assert f"HTTP {status}" in str(error.value)
    assert "synthetic-secret" not in str(error.value)
    assert "private provider body" not in str(error.value)
    if status == 404:
        assert "--list-models" in str(error.value)


def test_missing_key_and_stub_never_call_provider(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("network must not be called")
    monkeypatch.setattr(httpx, "post", unexpected)
    with pytest.raises(ValueError, match="PM_PROVIDER_KEY"):
        smoke(config(provider_key=""))
    with pytest.raises(ValueError, match="PM_PROVIDER=compatible"):
        smoke(config(provider="stub"))


def test_list_models_uses_discovery_endpoint_without_generation(monkeypatch):
    def get(endpoint, **kwargs):
        assert endpoint.endswith("/v1beta/openai/models")
        assert kwargs["follow_redirects"] is False
        return httpx.Response(200, json={"data": [{"id": "synthetic-model"}]})
    monkeypatch.setattr(httpx, "get", get)
    assert list_models(config()) == ["synthetic-model"]


def test_cli_redacts_network_error(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["gemini_smoke"])
    monkeypatch.setattr("scripts.gemini_smoke.Settings", config)
    def fail(*args, **kwargs):
        raise httpx.ConnectError("synthetic-secret")
    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(SystemExit):
        main()
    assert "synthetic-secret" not in capsys.readouterr().err
