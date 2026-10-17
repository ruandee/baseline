# Patient Memory Backend

A working synthetic-data backend for nursing-note and patient-record memory. Import sources, process immutable versions, ask cited questions, generate a handover summary, and reproduce what was known before a correction.

**Status: research prototype using fictional records.** PostgreSQL access controls, evidence spans, temporal queries and failure behavior are tested. Clinical validation and real semantic embeddings are not implemented.

## Run locally

Prerequisites: Python 3.12?3.14, uv 0.13.1, Docker Desktop/Compose, and Git. Windows: install uv with `python -m pip install --user uv`; use `python -m uv` if uv is outside PATH.

```powershell
uv sync --frozen
docker compose up -d --wait db object-store
uv run alembic upgrade head
uv run uvicorn patient_memory.api:app --host 127.0.0.1 --port 8000 --no-access-log
```

In another terminal:

```powershell
uv run python -m scripts.demo
```

The demo bootstraps a synthetic identity, creates/assigns a patient through the API, processes a note, asks a question, applies a correction, then asserts that current and historical answers differ correctly. Default stub mode needs no key or external model calls.

Interactive API docs: <http://127.0.0.1:8000/docs>. The [OpenAPI contract](docs/openapi.json) is committed.

## Local Ollama

The native Ollama adapter uses structured evidence selection with thinking disabled. Answers stay verbatim and cited. The initial trial uses `qwen3.5:0.8b`, a small engineering baseline, not a clinical recommendation.

If installed, run `ollama serve` and `ollama pull qwen3.5:0.8b`. The optional Windows script downloads the official portable release, checks its published SHA-256 and keeps local files outside Git:

```powershell
./scripts/start-ollama.ps1 -Architecture arm64 -TextOnly
```

Use `-Architecture amd64` for Intel/AMD Windows PCs. ARM64 is tested on the development laptop. `-TextOnly` imports pinned primary weights without the optional vision/draft layers; its local model name is `patient-memory-qwen35:0.8b`. For a regular full Ollama pull, omit `-TextOnly` and use `qwen3.5:0.8b` as the configured model. Configure `.env`, then restart the API:

```dotenv
PM_ENVIRONMENT=synthetic
PM_PROVIDER=ollama
PM_PROVIDER_URL=http://127.0.0.1:11434
PM_PROVIDER_MODEL=patient-memory-qwen35:0.8b
```

`PM_PROVIDER=stub` restores offline generation. Tests force stub mode; configured evaluations explicitly use your model. See [model adapter details](docs/decisions/002-model-adapters.md) and [measured local trial results](docs/local-model-results.md).

## Load data and run workers

```powershell
uv run python -m scripts.load_fixtures
uv run python -m patient_memory.worker --tenant <tenant-uuid> --actor <importer-uuid>
```

The loader prints IDs and short-lived synthetic tokens for 12 longitudinal patients across two tenants. Use a token with Swagger's Authorize button. Fixtures include nursing and patient reports, structured observations, earlier expired observations and amendments. The loader processes its own imports; a worker handles subsequent API imports.

## Verify

```powershell
uv run ruff check .
uv run pytest tests
uv run python -m evals.run --suite synthetic --provider stub --output artifacts/eval.json
uv run python -m evals.run --suite synthetic --provider configured --max-questions 5 --output artifacts/local-model.json
```

The fixture suite has 60 authored questions. [Evaluation results](docs/evaluation-results.md) preserve the initial retrieval failure and distinguish corrected regression results from untouched held-out estimates. CI runs deterministic tests, DB integration and offline evaluation.

## Architecture and review

FastAPI/Pydantic + PostgreSQL 17/pgvector + a leased jobs worker + S3 source storage. Compose uses LocalStack S3. Runtime queries use a non-owner role with row-level security. Event time and system knowledge time are separate. Every assertion resolves to an immutable source span.

- [Product scope](docs/01-product.md)
- [Architecture and data](docs/02-architecture.md)
- [API contracts](docs/03-contracts.md)
- [Evaluation plan](docs/04-evaluation.md)
- [Implementation milestones](docs/05-build-plan.md)
- [Operations, recovery and limitations](docs/operations.md)
- [Agent instructions](AGENTS.md)

Implementation commits are separated by milestone on `build/backend-mvp`. The review handoff records completion and remaining work; the original specification stays available for comparison.

## Local patient workspace (F01)

After starting Docker services and applying migrations, launch the frontend:

```sh
uv run python -m scripts.frontend
```

Open <http://127.0.0.1:8001>. This command seeds 12 fictional profiles idempotently
and serves a responsive patient list, filtered timeline, cited questions, source
inspection, and shift handover summaries. The same FastAPI backend serves the UI
and API on port 8001; the original API on port 8000 can remain running independently.
No Node build or external assets are required.

The workspace is **local-only and synthetic-only**. It uses an assigned read-only
nurse identity, an in-memory browser bearer token, and the offline provider. The
session endpoint rejects remote clients, non-loopback Host headers, and cross-origin
requests. Do not expose this developer server through a tunnel or use real records.
Display names are fictional UI aliases; they are not demographics from source data.
The initial record snapshot is January 2, 2026; all UI times and shift inputs are UTC.
Refreshing the page renews the eight-hour synthetic token. Patient edits, imports,
production sign-in, and live model integration are outside this frontend milestone.

Validation: `uv run pytest tests` includes demo-origin and read-only authorization
checks. `node --check frontend/app.js` checks browser JavaScript syntax when Node is
available. Browser verification covers patient switching, citations, handover,
missing evidence, filtering, search, and responsive layout.

