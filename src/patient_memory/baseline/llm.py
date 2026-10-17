"""Bounded schema requests. Callers validate output and own deterministic fallbacks."""
import json
import time

import httpx

MAX_INPUT_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
TIMEOUT_S = 15


def request_json(cfg, *, schema_name: str, schema: dict, system: str, user: str) -> dict:
    if cfg.provider not in {"compatible", "ollama"}:
        raise ValueError("provider_disabled")
    if len((system + user).encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("provider_input_too_large")
    native = cfg.provider == "ollama"
    payload = {"model": cfg.provider_model, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}]}
    if native:
        payload.update(format=schema, stream=False, think=False,
                       options={"temperature": 0, "num_predict": 2048, "num_ctx": 16384})
    else:
        payload.update(temperature=0, max_tokens=2048, response_format={
            "type": "json_schema", "json_schema": {
                "name": schema_name, "strict": True, "schema": schema}})
    headers = {"Authorization": "Bearer " + cfg.provider_key} if cfg.provider_key else {}
    endpoint = "/api/chat" if native else "/chat/completions"
    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT_S, connect=3), follow_redirects=False,
                      trust_env=False) as client:
        with client.stream("POST", cfg.provider_url.rstrip("/") + endpoint,
                           json=payload, headers=headers) as response:
            if not 200 <= response.status_code < 300:
                raise ValueError("provider_unavailable")
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("provider_response_too_large")
                if time.monotonic() - started > TIMEOUT_S:
                    raise ValueError("provider_timeout")
    try:
        body = json.loads(raw)
        content = body["message"]["content"] if native else body["choices"][0]["message"]["content"]
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("invalid_provider_response")
        return result
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("invalid_provider_response") from exc
