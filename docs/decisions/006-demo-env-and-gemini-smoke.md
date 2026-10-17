# BL-01: Demo environment and Gemini smoke test

The synthetic demo now mints tokens using `PM_TOKEN_TTL_HOURS`, defaulting to the
48-hour Baseline demo value. The general application rate-limit default remains 30;
the checked-in `.env.example` sets the demo override to 600 so production-like
defaults are not silently widened.

Gemini is configured through the existing compatible provider adapter. The example
environment documents the OpenAI-compatible endpoint, model and secret key without
committing credentials. `scripts/gemini_smoke.py` sends a minimal strict JSON-schema
chat request and validates both the envelope and the returned object with Pydantic.
It fails clearly when the provider is stubbed or no key is configured. The script
does not run in CI and no network call is made by tests.

The smoke script uses `response_format.type=json_schema`, matching the existing
compatible selector. If Gemini rejects that field, the failure is the signal to add
a native Gemini request in the future `baseline/llm.py`; this ticket does not hide
or weaken that provider incompatibility.
