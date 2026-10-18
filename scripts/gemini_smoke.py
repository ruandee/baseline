"""Verify the configured Gemini OpenAI-compatible endpoint with a strict JSON response."""
import argparse
import json

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from patient_memory.config import Settings


class SmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    safe: bool


def provider_base(cfg: Settings) -> str:
    if cfg.provider != "compatible":
        raise ValueError("Set PM_PROVIDER=compatible before running the Gemini smoke test")
    if not cfg.provider_key:
        raise ValueError("PM_PROVIDER_KEY is required for the Gemini smoke test")
    return cfg.provider_url.rstrip("/")


def checked_response(response: httpx.Response):
    if response.status_code == 404:
        raise ValueError(
            "Provider returned HTTP 404: verify PM_PROVIDER_URL ends in /v1beta/openai "
            "for Gemini and PM_PROVIDER_MODEL is available to this key. "
            "Run with --list-models to inspect available model IDs."
        )
    if response.is_error or response.is_redirect:
        raise ValueError(f"Provider returned HTTP {response.status_code}; no response body logged")
    try:
        return response.json()
    except ValueError as exc:
        raise ValueError("Provider returned invalid JSON") from exc


def list_models(cfg: Settings) -> list[str]:
    endpoint = provider_base(cfg) + "/models"
    response = httpx.get(
        endpoint, headers={"Authorization": "Bearer " + cfg.provider_key},
        timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False,
    )
    body = checked_response(response)
    try:
        models = body["data"]
        if not isinstance(models, list):
            raise ValueError("Invalid model list")
        identifiers = [model["id"] for model in models]
        if not all(isinstance(identifier, str) and identifier for identifier in identifiers):
            raise ValueError("Invalid model ID")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Provider returned an invalid model list") from exc
    return identifiers


def smoke(cfg: Settings) -> SmokeResponse:
    endpoint = provider_base(cfg) + "/chat/completions"
    schema = SmokeResponse.model_json_schema()
    payload = {
        "model": cfg.provider_model,
        "temperature": 0,
        "max_tokens": 100,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "baseline_smoke", "strict": True, "schema": schema}},
        "messages": [
            {"role": "system", "content": "Return only the requested JSON object."},
            {"role": "user", "content": "Say hello. This is a connectivity test."},
        ],
    }
    response = httpx.post(
        endpoint, json=payload, headers={"Authorization": "Bearer " + cfg.provider_key},
        timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False,
    )
    body = checked_response(response)
    try:
        content = body["choices"][0]["message"]["content"]
        result = SmokeResponse.model_validate_json(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("Gemini returned a response that failed the smoke schema") from exc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the validated response as JSON")
    parser.add_argument("--list-models", action="store_true", help="List model IDs without generation")
    args = parser.parse_args()
    try:
        cfg = Settings()
        if args.list_models:
            print(json.dumps(list_models(cfg)))
            return
        result = smoke(cfg)
    except ValueError as exc:
        # Settings validation can include environment values; never print its contents.
        parser.exit(1, "Invalid provider configuration\n" if isinstance(exc, ValidationError)
                    else f"{exc}\n")
    except httpx.RequestError:
        parser.exit(1, "Provider connection failed; check network and configured endpoint\n")
    print(json.dumps(result.model_dump()) if args.json else "Gemini smoke test passed: " + result.answer)


if __name__ == "__main__":
    main()
