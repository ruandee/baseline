# Patient Memory Backend

A working synthetic-data backend for nursing-note and patient-record memory. Import sources, process immutable versions, ask cited questions, generate a handover summary, and reproduce what was known before a correction.

**Status: research prototype using fictional records.** PostgreSQL access controls, evidence spans, temporal queries and failure behavior are tested. Clinical validation and real semantic embeddings are not implemented.

## Baseline (hackathon build)

Baseline adds a 10-second voice check to this backend: it measures speech timing and pitch,
compares them with the same resident's own history, checks the record for context, and lets a
fixed rule table pick a verdict (`escalate`, `watch`, `explained`, `within_normal`, `enrolling`).
Statistics detect change; rules choose the verdict; the language model only tags note context and
(once BL-12 lands) assembles a validated SBAR draft. It is a synthetic-data prototype: it does not
diagnose, suggest treatment, or claim clinical validation. Spec: [docs/06-baseline.md](docs/06-baseline.md);
current status: [docs/build-status.md](docs/build-status.md); tracker: issue #38.

What is on `main` today versus still pending (check the tracker before relying on this list):

| Area | On `main` | Pending (not merged) |
| --- | --- | --- |
| Speech pipeline and `POST /v1/patients/{id}/checks` | Yes (BL-04, BL-05, BL-07) | Real-voice golden clips (BL-06, on hold); p95 latency on a host |
| Change engine, verdicts, assessments, shift budget | Yes (BL-08, BL-11) | Engine policy proposal (PR #60) is not approved |
| Context tags, note extraction with offline fallback | Yes (BL-09, BL-10) | Live Gemini acceptance |
| `GET /v1/watchlist`, `GET /v1/patients/{id}/overview` | Yes (BL-13) | |
| Validated SBAR draft | Template SBAR only | BL-12 (PR #57) |
| Frontend `/unit` | Yes (BL-18) | Integrated acceptance with the cohort |
| Frontend `/check`, `/resident/{id}` | Shell routes only | BL-17 (PR #50), BL-19 (PR #55) |
| 12-resident synthetic cohort loader | No | BL-14 (PR #53) |
| Demo reset script | No | BL-21 |
| HTTPS host (Compose + Caddy) | No | BL-20 (PR #54) |
| Vox Advantage adapter | No | BL-32; it is a **mock** contract, there is no real Vox/PointClickCare integration |
| KAZE safety sessions | No | BL-25 to BL-29; not integrated |

Until BL-14, BL-17, BL-19, BL-20 and BL-21 merge, a clean clone cannot reproduce the full Baseline
stage demo. What a clean clone can run today is below.

## Run locally

Prerequisites: Python 3.12-3.14, uv 0.13.1, Docker Desktop/Compose, Git, and `ffmpeg` on PATH
(voice checks decode uploads with it; CI installs it). Windows: install uv with
`python -m pip install --user uv`; use `python -m uv` if uv is outside PATH. Configuration is read
from `PM_*` environment variables or a local `.env` (copy `.env.example`; never commit `.env`).
The defaults are synthetic-only and use the offline stub provider. On first start the API loads
the Whisper `base` model through faster-whisper, which downloads it once from Hugging Face; if
that fails the API still starts and voice checks retry the load.

```powershell
git clone https://github.com/ruandee/patient-memory-backend.git
cd patient-memory-backend
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
uv run pytest tests/unit                                   # no services needed
uv run pytest tests/integration tests/contract tests/e2e   # needs db + object-store up and migrated
uv run python -m evals.run --suite synthetic --provider stub --output artifacts/eval.json
# Optional, calls your configured model; never part of CI:
uv run python -m evals.run --suite synthetic --provider configured --max-questions 5 --output artifacts/local-model.json
```

This is the same order CI runs (`.github/workflows/checks.yml`). Audio contract tests need
`ffmpeg`; Whisper-based tests are marked `slow` and deselected by default.

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

The same server also serves the Baseline shell at `/unit`, `/check` and `/resident/{id}`
([decision 005](docs/decisions/005-baseline-frontend-location.md)). On `main`, `/unit` reads the
live watch list; it lists the workspace's fictional patients with no verdict until voice checks
are recorded for them, because the Baseline cohort loader (BL-14) is not merged. `/check` and `/resident/{id}` render placeholders
until BL-17 and BL-19 merge. Hosted (off-loopback) mode needs `PM_FRONTEND_HOSTS` and a
pre-minted `PM_DEMO_TOKEN` signed with a deployment-only `PM_JWT_SECRET`; never host with the
default secret, which is public in this repository.

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

