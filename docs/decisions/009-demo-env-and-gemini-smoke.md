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


## Takeover validation and unresolved provider gate

The main-branch merge preserves audio-retention configuration and the BL-07 status.
Decision numbering moves this record to 009; 006 is the voice-upload decision.
Token expiry uses one issuance timestamp and a positive configurable lifetime.
Parameterized tests exercise 1, 7, 48 and 72 hours through PM_TOKEN_TTL_HOURS,
and verify that an expired token is rejected.

The previous live request returned HTTP 404. Google's documented compatible base
is `https://generativelanguage.googleapis.com/v1beta/openai/`:
https://ai.google.dev/gemini-api/docs/openai . The smoke request already uses that
route; a 404 alone cannot distinguish a wrong route from an unavailable model.
There is no saved provider key in this workspace, so successful live compatibility
is **unverified**, rather than inferred from stub tests. No fallback model is chosen.

Configure PM_PROVIDER=compatible, PM_PROVIDER_URL, PM_PROVIDER_MODEL and
PM_PROVIDER_KEY locally (never in Git). Run:

```sh
uv run python -m scripts.gemini_smoke --list-models
uv run python -m scripts.gemini_smoke --json
```

Model discovery performs GET /models without a generation request. Check the
configured model against those IDs before retrying generation. The CLI reports
HTTP status without provider bodies, request logs or credentials; 404 includes
these recovery steps. It rejects redirects and strict-schema violations (including
string booleans). Deterministic mocked HTTP tests cover route, schema, malformed
responses, status failures, model discovery and missing-key behavior. The smoke
request remains bounded to 100 output tokens and one generation call per run.

Local validation: frozen sync and lint passed; unit tests 68 passed, 7 skipped
(ffmpeg unavailable), 2 slow deselected. Docker is absent, so database-backed
checks and stub evaluation require CI or a service-enabled host. Real Gemini
validation awaits a locally supplied key. Do not close BL-01 on stub results alone.

Model example updated to gemini-3.8-flash following Google model guidance for new projects;
2.5 model access is limited to previous users. See https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash .
