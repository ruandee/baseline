# Patient Memory Backend

A working synthetic-data backend for nursing-note and patient-record memory. Import sources, process immutable versions, ask cited questions, generate a handover summary, and reproduce what was known before a correction.

**Status: research prototype using fictional records.** PostgreSQL access controls, evidence spans, temporal queries and failure behavior are tested. Clinical validation and real semantic embeddings are not implemented.

## Baseline (hackathon build)

Baseline measures speech timing and pitch, compares a check with the same person's own
history, checks documented context, and applies fixed rules to return `escalate`, `watch`,
`explained`, `within_normal` or `enrolling`. The model can tag cited note context and assemble
validated SBAR sentences; it does not choose the verdict. This is an engineering prototype
using fictional records, without clinical validation, diagnosis or treatment recommendations.

Start here:

- [Hosted unit dashboard](https://baseline.deeruan.com/unit): twelve fictional residents,
  resident charts, cited evidence, documented temperature and preliminary handoff/export.
- [Three-day presentation](https://baseline.deeruan.com/check?mode=live&demo=days): record or
  import a local clip, then show clearly labelled scripted Watch, Explained and Escalate
  examples. Audio stays in the tab; these outcomes are authored, not measured from the clip,
  and are never stored as assessments. See the [presentation guide](docs/live-voice-demo.md).
- [Deploy from a clean clone](docs/deployment-walkthrough.md): Linux server, Docker Compose,
  DNS/HTTPS, private credential bootstrap, twelve-resident load and verification. Use the
  reviewed release SHA; an older deployment does not gain new features from a query string.
- [Current status and acceptance gates](docs/build-status.md),
  [live tracker #38](https://github.com/ruandee/patient-memory-backend/issues/38),
  [specification](docs/06-baseline.md) and [product context](docs/07-baseline-proposal.md).

The reviewed integration is on `main` through PR #104 (merge `250cd51`; tested release head
`f7f02c0`). Exact-head CI passed 634 unit tests, 381 database-backed tests, migrations, stub
evaluation and image smoke. These results do not establish physical-phone or hosted-latency
acceptance. Check the tracker for the current deployed revision and rehearsal status.

| Implemented on `main` | Remaining acceptance |
| --- | --- |
| Speech upload, local Whisper/prosody, quality gates and deterministic change/verdict engine | Physical-phone capture, usable personal baselines and warm hosted p95 below five seconds |
| Twelve-resident loader, watch list, resident charts, exact source/check readback and grounded multimodal SBAR/export | Full hosted rehearsal; export remains preliminary, with no EHR writeback |
| English counting profiles, explicit permission, score-free PSW flow and trusted asserted note authorship | Nontechnical resident/PSW testing; unsupported languages stop explicitly |
| Fixture-only current-time reset, separate capture identities, Compose/HTTPS and dedicated workers | Hosted reset under one minute; reset must refuse unexpected recordings instead of deleting them |
| KAZE session, three-clip activation, explicit self-custody voice permission, scheduler, SMS/ack and pages | Two phones, consenting recipient, actual SMS delivery/ack and rehearsals; default sender is simulation |
| Registered resting vitals, local movement processing and Vox mock adapter | Physical chair/movement acceptance and real mock-fixture capture; no Vox/PointClickCare integration |
| Optional real-audio golden suite and approved protocol | Local run evidence is separate from hosted capture; raw recordings stay outside Git/CI |

For a genuine voice comparison, follow the [separate enrollment flow](docs/live-voice-demo.md#optional-genuine-baseline-comparison-separate-flow).
Use a dedicated capture identity outside the twelve scripted residents, explicitly configure
English and record actual permission, then enroll five distinct rested recordings. A later
speaker needs their own baseline. An ordinary telephone call is not ingested by the app:
record on the caller's device using the app. Results are actual measurements, with no promised
change or escalation. The local scripted presentation above needs no personal enrollment.

Backup video, two complete rehearsals, phone/LTE checks, Devpost submission and the KAZE
recipient test remain human acceptance work. See [rehearsal checklist](docs/submission/rehearsal-checklist.md).

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

Implementation uses reviewed feature branches and milestone commits. The build-status ledger and tracker distinguish merged behavior from acceptance still requiring a host, device or person; the original specification remains available for comparison.

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

The same server serves Baseline at `/unit`, `/check`, `/resident/{id}`, `/out` and session
pages ([decision 005](docs/decisions/005-baseline-frontend-location.md)). The local workspace
loader and the Baseline storyline loader use different synthetic tenants. To reproduce the
complete twelve-resident Baseline demo, use the explicit bootstrap/load steps in the
[hosting recipe](docs/demo-hosting.md) or the [beginner walkthrough](docs/deployment-walkthrough.md),
rather than expecting the generic workspace seed to contain voice assessments.

Default workspace mode is local-only: assigned read-only nurse access, an in-memory browser
token and stub provider. Off-loopback hosting is explicitly opt-in through `PM_FRONTEND_HOSTS`
and private pre-minted credentials signed with a deployment-only `PM_JWT_SECRET`. The Compose
workflow provisions separate nurse, PSW and KAZE identities; their roles are not interchangeable.
Never host with the repository's public default secret. Follow the deployment guide instead of
exposing a default developer server through a tunnel. Only fictional records belong in this demo.

Validation: `uv run pytest tests` includes demo-origin and read-only authorization
checks. `node --check frontend/app.js` checks browser JavaScript syntax when Node is
available. Browser verification covers patient switching, citations, handover,
missing evidence, filtering, search, and responsive layout.

