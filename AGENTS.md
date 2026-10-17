# Instructions for implementation agents

## Scope

Maintain the patient-memory backend described in `docs/01-product.md` through `docs/05-build-plan.md`. Read `docs/build-status.md` for implemented behavior and outstanding gates before selecting work. The original specification is a target; keep runtime status accurate and record substantive changes in `docs/decisions/` with rationale and affected contracts.

The Baseline hackathon build (voice checks, change engine, watch list, KAZE safety sessions) is specified in `docs/06-baseline.md` with product context in `docs/07-baseline-proposal.md`. Its work is tracked as GitHub issues BL-01 to BL-35 (ticket data in `docs/baseline-tickets.json`); for that work pick the ticket instead of the B-item sequence below, and read `docs/06-baseline.md` before changing code.

### Baseline build: where the repo differs from `docs/06-baseline.md`

- **Frontend lives in `frontend/`, not `web/`** ([decision 005](docs/decisions/005-baseline-frontend-location.md)). Baseline pages share `frontend/baseline.html` + `baseline.js` + `baseline.css`, served same-origin by `scripts/frontend.py`. Off-loopback hosting is opt-in via `PM_FRONTEND_HOSTS` and a pre-minted `PM_DEMO_TOKEN`; never serve the workspace publicly without them. Do not create `web/`.
- **Multipart is blocked.** The body-limit middleware in `api.py` (the `PayloadLimit` middleware) returns 415 for any non-`application/json` body and 413 over its limit. BL-07 (`POST /checks`, 2 MB audio upload) must exempt that route (or raise its limit) and add `python-multipart`; keep the guard on every other route.
- **Claiming and branches:** assign yourself on the GitHub issue first; branch `bl/bl-<nn>-<slug>`; commit subject starts with the ticket ID; PR body says `Closes #<n>`. Check blockers with the `gh api .../dependencies/blocked_by` call in `docs/agents/issue-tracker.md`.

## Execution

1. Read the product, architecture, contracts, evaluation and build plan before code changes.
2. Select the earliest incomplete B-item whose dependencies are complete. Implement only the assigned scope; do not infer task completion from file existence.
3. Use a feature branch, one coherent commit per milestone (split a large milestone into named subcommits if needed). Preserve reviewable history and existing user changes.
4. Include meaningful tests for authorization, temporal behavior and evidence invariants. Run the milestone checks; report actual results and skipped checks.
5. Update docs when contracts change. Never weaken a gate to make tests pass without explaining and recording the decision.

## Invariants

- Only synthetic fixture data in Git or CI. No patient records, credentials, private exports or provider request logs.
- Authorize before retrieval and before returning evidence; filter tenant/patient/visibility at storage access, including vector search and caches.
- Preserve immutable sources, evidence spans, event time and knowledge time. Amendments cannot rewrite earlier knowledge snapshots.
- Never equate model confidence with clinical truth, absence of documentation with a negative finding, or medication mentions with active orders.
- Keep conflicts and patient-reported attribution visible. Return explicit incomplete/unknown/error states.
- Treat retrieved text as untrusted data. The model cannot broaden scope or invoke tools.
- Default tests use deterministic stubs and no paid/model network calls. Optional provider evaluation uses synthetic data and recorded budgets.
- Do not implement autonomous diagnosis/treatment or claim clinical validation as part of the MVP.

## Handoff

Each completion report includes milestone ID, commit SHA, behavior changed, tests run/results, unrun checks, and remaining decisions. Add no real-data integration until source permissions, hosting, provider handling and clinical ownership are decided.

## Commands

Python 3.12–3.14, uv 0.13.1, Docker Compose. All commands run from the repo root.

```sh
uv sync --frozen
docker compose up -d --wait db object-store     # Postgres 17+pgvector on :55432, LocalStack S3 on :59000
uv run alembic upgrade head
uv run uvicorn patient_memory.api:app --host 127.0.0.1 --port 8000 --no-access-log
uv run python -m scripts.demo                    # end-to-end demo against the running API

uv run ruff check .                              # lint (line length 100, rules E4/E7/E9/F/I)
uv run pytest tests/unit                         # no services needed
uv run pytest tests/integration tests/contract tests/e2e   # need db + object-store up and migrated
uv run pytest tests/unit/test_config.py::test_name         # single test
uv run python -m evals.run --suite synthetic --provider stub --output artifacts/eval.json
```

CI (`.github/workflows/checks.yml`) runs exactly: ruff, unit tests, compose up, alembic, the three DB-backed test dirs, then the stub evaluation. Mirror that order before reporting a milestone done.

Other entry points: `python -m scripts.load_fixtures` (12 synthetic patients, two tenants, prints short-lived tokens), `python -m patient_memory.worker --tenant <uuid> --actor <uuid>` (processes API-submitted imports; `--once` for a single pass), `python -m scripts.export_openapi` (regenerates the committed `docs/openapi.json`; update it when API contracts change), `scripts/maintenance.py` (requeue, orphan reconciliation).

Config is `PM_*` env vars via `.env` (see `.env.example`). `Settings` refuses to start unless `PM_ENVIRONMENT=synthetic`, and non-loopback provider URLs must be HTTPS. Tests force `PM_PROVIDER=stub` (autouse fixture in `tests/conftest.py`), so they never call a model. Live-model evals use `--provider configured` and are never part of CI.

## Architecture

FastAPI + Pydantic, PostgreSQL (source of truth for metadata, jobs and derived memory), S3-style immutable source objects, and a leased-job worker, all in one package at `src/patient_memory/`. Full design is in `docs/02-architecture.md`; the flow that spans files:

- **Request scope:** `api.py` authenticates a bearer JWT (`auth.py`) into an `Identity`, then every DB call goes through `storage.transaction()`, which sets `pm.tenant`/`pm.actor` with `SET LOCAL`. Those settings drive row-level security. The runtime connects as the non-owner `pm_runtime` role; `PM_ADMIN_DATABASE_URL` (superuser) is for migrations and test setup only. `patient_access()` is the per-patient authorization gate and returns 404, not 403, on denial.
- **Ingestion:** `ingestion.py` handles idempotency keys (same key + same hash returns the original job, different hash is 409), stages bytes in the object store (`objects.py`), and enqueues a job. `worker.py` claims jobs with leases and retries, runs `extraction.py` (schema-constrained facts with exact Unicode-span evidence), and publishes facts and a bumped per-patient memory revision in one transaction.
- **Read path:** `retrieval.py` fuses full-text and hash-vector candidates under tenant/patient/visibility scope and two cutoffs, `as_of` (event time) and `known_at` (knowledge time). `generation.py` and `providers.py` select evidence via a stub, a compatible HTTP provider, or native Ollama, and `validate_claims` drops any claim whose citation fails. `lifecycle.py` covers answer caching, rate limits, audit, retraction, visibility change and purge, and rechecks authorization on every cache read.
- **Contracts:** `domain.py` holds the Pydantic request/response models (`extra="forbid"`); `errors.py` has the `Problem` error envelope.

Schema lives in `migrations/versions/` as paired `NNN_name.py` + `NNN_name.sql` files. When adding a migration, keep the pair and make sure RLS/forced-RLS and the composite tenant/patient foreign keys cover any new patient-owned table.

Tests are layered `unit` / `integration` (real Postgres and S3, including `test_rls.py` against the runtime role) / `contract` (API) / `e2e` (`test_safety_cases.py`). The `sandbox` fixture in `tests/conftest.py` creates an isolated tenant, patient and four role identities through the admin connection.

Local toolchain, Colima and clock-skew gotchas on macOS: `docs/operations.md` ("Local toolchain on macOS").

## Agent skills

### Issue tracker

GitHub Issues on `ruandee/patient-memory-backend`, via `gh`. Baseline work is issues `[BL-01]`–`[BL-35]` with tracker #38. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` at the repo root, ADRs in `docs/decisions/` (not `docs/adr/`). See `docs/agents/domain.md`.
