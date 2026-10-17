"""Verify the configured Gemini OpenAI-compatible endpoint with a strict JSON response."""
import argparse
import json

import httpx
from pydantic import BaseModel, ConfigDict

from patient_memory.config import Settings


class SmokeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str
    safe: bool


def smoke(cfg: Settings) -> SmokeResponse:
    if cfg.provider != "compatible":
        raise ValueError("Set PM_PROVIDER=compatible before running the Gemini smoke test")
    if not cfg.provider_key:
        raise ValueError("PM_PROVIDER_KEY is required for the Gemini smoke test")
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
    endpoint = cfg.provider_url.rstrip("/") + "/chat/completions"
    response = httpx.post(
        endpoint, json=payload, headers={"Authorization": "Bearer " + cfg.provider_key},
        timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False,
    )
    response.raise_for_status()
    body = response.json()
    try:
        content = body["choices"][0]["message"]["content"]
        result = SmokeResponse.model_validate_json(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("Gemini returned a response that failed the smoke schema") from exc
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print the validated response as JSON")
    args = parser.parse_args()
    result = smoke(Settings())
    print(json.dumps(result.model_dump()) if args.json else "Gemini smoke test passed: " + result.answer)


if __name__ == "__main__":
    main()
