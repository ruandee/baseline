# Test suite guide

The suite covers the patient-memory backend and Baseline features: authorization/RLS, immutable
evidence, speech scoring and context, KAZE sessions/SMS, motion/vitals, browser behavior and hosted
deployment. Parametrized inputs account for many collected cases; a test count is not a count of
separate test functions. Test sources and synthetic fixtures occupy well under 1 MiB. Python
bytecode caches and private golden recordings are not tracked test sources.

## Choose the check for your change

| Scope | Command | Services |
| --- | --- | --- |
| All offline Python and browser logic | `uv run pytest tests/unit` | None; Node for browser suites |
| Frontend logic only | `uv run pytest tests/unit/test_frontend_js.py` | Node; no real mic/camera/network |
| One browser suite | `node --test tests/js/demo_handoff.test.js` | Node |
| One backend feature | `uv run pytest tests/unit/test_engine.py` | None |
| API/storage/evidence integration | `uv run pytest tests/integration tests/contract tests/e2e` | Migrated PostgreSQL and object store |
| Optional recorded-audio gates | `uv run pytest -m slow tests/unit/test_golden_clips.py -v -rA` | Local tools/model and private clips |

The five optional slow cases are excluded by default. They are not replaced by stub tests or
made into default CI model calls. Use the operator guide for the current golden protocol.

## Browser tests have one launcher

`tests/unit/test_frontend_js.py` discovers every `tests/js/*.test.js` and `*.test.mjs` suite and
runs them in one Node invocation. This replaces eight standalone wrapper files and launchers
embedded in four other Python modules. The JavaScript files and their assertions are unchanged.
Pytest reports the batch as one test; Node still executes and reports each underlying case.
Node absence skips browser execution explicitly, as before. A failed or empty Node run fails.

`tests/js_runner.py` also runs selected suites with real API-captured fixtures for the watchlist,
resident evidence and multimodal handoff contracts. Those service-backed checks are intentional:
offline DOM fixtures cannot establish that real authorized responses carry the right evidence.
Helpers no longer have to be imported from Python test modules.

## Release checks still run in full

Focused commands help iteration; they do not replace the release checks. Keep CI order: Ruff,
frontend syntax, unit tests, storage startup, migrations, integration/contract/e2e tests, then
synthetic stub evaluation. Full service-backed runs also include DB/object-store setup and
isolated tenant fixtures, so they take longer than the offline suite. Preserve authorization,
temporal, consent and evidence cases when simplifying the suite.
