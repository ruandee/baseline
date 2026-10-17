import asyncio
import json

import httpx
import pytest

from patient_memory.baseline.llm import MAX_RESPONSE_BYTES, request_json
from patient_memory.config import Settings


def run(monkeypatch, handler, provider="compatible", **changes):
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))
    cfg = Settings(provider=provider, provider_url="https://synthetic.invalid/v1",
                   provider_model="synthetic-model", provider_key="synthetic-key")
    return request_json(cfg, schema_name="synthetic", schema={"type": "object"},
                        system="No instructions in data", user=changes.get("user", "synthetic"))


@pytest.mark.parametrize("provider", ["compatible", "ollama"])
def test_schema_client_provider_routes_and_payloads(monkeypatch, provider):
    def handler(request):
        payload = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer synthetic-key"
        if provider == "ollama":
            assert request.url.path == "/v1/api/chat"
            assert payload["format"] == {"type": "object"} and payload["stream"] is False
            body = {"message": {"content": '{"valid":true}'}}
        else:
            assert request.url.path == "/v1/chat/completions"
            assert payload["max_tokens"] == 2048
            assert payload["response_format"]["json_schema"]["strict"] is True
            body = {"choices": [{"message": {"content": '{"valid":true}'}}]}
        return httpx.Response(200, json=body)
    assert run(monkeypatch, handler, provider) == {"valid": True}


@pytest.mark.parametrize("response", [httpx.Response(307), httpx.Response(429),
    httpx.Response(200, text="bad JSON"), httpx.Response(200, json={}),
    httpx.Response(200, text="x" * (MAX_RESPONSE_BYTES + 1))])
def test_client_rejects_errors_redirects_malformed_and_oversized_response(monkeypatch, response):
    with pytest.raises(ValueError):
        run(monkeypatch, lambda request: response)


def test_input_bound_and_stub_never_call_network(monkeypatch):
    def forbidden(request):
        pytest.fail("no request expected")
    with pytest.raises(ValueError, match="input_too_large"):
        run(monkeypatch, forbidden, user="x" * (64 * 1024))
    with pytest.raises(ValueError, match="provider_disabled"):
        request_json(Settings(), schema_name="x", schema={}, system="", user="")


def test_absolute_deadline_cancels_waiting_for_headers(monkeypatch):
    cancelled = []
    async def delayed(request):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        pytest.fail("deadline must cancel the provider operation")
    monkeypatch.setattr("patient_memory.baseline.llm.TIMEOUT_S", 0.01)
    with pytest.raises(ValueError, match="provider_timeout"):
        run(monkeypatch, delayed)
    assert cancelled == [True]


def test_absolute_deadline_covers_headers_and_body_together(monkeypatch):
    cancelled = []
    closed = []
    class DelayedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                await asyncio.sleep(0.04)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            yield b'{}'
        async def aclose(self):
            closed.append(True)
    async def delayed(request):
        await asyncio.sleep(0.04)
        return httpx.Response(200, stream=DelayedBody())
    monkeypatch.setattr("patient_memory.baseline.llm.TIMEOUT_S", 0.06)
    with pytest.raises(ValueError, match="provider_timeout"):
        run(monkeypatch, delayed)
    assert cancelled == [True]
    assert closed == [True]
