# Baseline

**Notice when someone seems different. Understand the change before interrupting care.**

Baseline is a long-term care decision-support prototype built around a short voice check.
It compares how a resident speaks with their own history, then looks for context in their
record so the care team can see what changed and why it was flagged.

Built for the PointClickCare **Catch It Early** hackathon challenge, on top of a patient-memory
backend that keeps answers connected to their original evidence.

**Research prototype. All resident records are fictional. Baseline is not clinically validated
and does not diagnose conditions or recommend treatment.**

## How it works

1. **Capture:** a care aide asks the resident to count to 20 and say the days of the week.
2. **Compare:** the speech pipeline measures speech rate, pause ratio, mean pause length and
   median pitch against that resident's own baseline.
3. **Explain:** the system checks documented context, such as medication changes and care notes.
4. **Review:** the nurse sees a ranked watch list, supporting evidence and a handoff draft.

A change can be marked **escalate**, **watch**, **explained**, **within normal** or **enrolling**.
The explained case matters: a change with documented context may not need an interruption.
Statistics detect change; fixed rules select the verdict. The language model finds note context
and can assemble a constrained handoff draft. Server checks reject unsupported quotes and claims,
and offline fallbacks keep the core flow available without a model provider.

## What's in the repository

- Voice capture and quality checks, personal baselines, change detection and a nurse watch list.
- A resident evidence view and grounded SBAR (Situation, Background, Assessment, Recommendation) drafts.
- A patient-memory API with cited answers, immutable sources, corrections and historical queries.
- Experimental motion and resting-vitals signals, plus Baseline Out / KAZE safety check-in sessions.
- Synthetic fixtures, deterministic tests and an optional HTTPS demo deployment.

These are implemented prototype paths, not claims of completed phone, camera, live-SMS or hosted
acceptance. See [runtime status and remaining gates](docs/build-status.md) for detailed evidence.
The Vox Advantage adapter is a **mock**, with no real PointClickCare integration. Vector retrieval
uses hash vectors; real semantic embeddings are not implemented.

## Run locally

You need Python **3.12-3.14**, **uv 0.13.1**, **Docker with Compose**, Git and **ffmpeg** on PATH.
Settings use `PM_*` environment variables or a local `.env`; defaults use synthetic data and the
stub provider. No model API key is needed. Speech checks download the Whisper `base` model on
first load, so first-time speech setup needs internet access.

```sh
git clone https://github.com/ruandee/patient-memory-backend.git
cd patient-memory-backend
uv sync --frozen
docker compose up -d --wait db object-store
uv run alembic upgrade head
uv run python -m scripts.frontend
```

Open **http://127.0.0.1:8001** for the seeded patient workspace, or **/unit** for the Baseline
watch list and **/check** for capture. The local workspace seeds fictional profiles; it does not
load the separate authored Baseline scenario cohort. See the [scenario loader guide](fixtures/synthetic/baseline_storylines.README.md)
for those fixtures and the [hosting guide](docs/demo-hosting.md) for wiring its roster into a demo.
Interactive API documentation is at **http://127.0.0.1:8001/docs**.

To run the API and its end-to-end memory demo separately:

```sh
uv run uvicorn patient_memory.api:app --host 127.0.0.1 --port 8000 --no-access-log
# In another terminal:
uv run python -m scripts.demo
```

Keep local development on loopback. Public hosting requires explicit host configuration,
deployment-only credentials and a pre-minted demo token; follow the
[deployment walkthrough](docs/deployment-walkthrough.md).

## Stack

| Layer | Technologies |
| --- | --- |
| Browser | HTML, CSS, JavaScript, SVG; MediaPipe for experimental motion capture |
| API | Python, FastAPI, Pydantic, Uvicorn |
| Data | PostgreSQL 17, TimescaleDB, pgvector, Psycopg, Alembic |
| Source storage | S3-compatible storage; LocalStack for the synthetic environment |
| Speech | ffmpeg, WebRTC VAD, faster-whisper, Praat/Parselmouth, NumPy, SoundFile |
| Model providers | Offline stub, Gemini through a compatible HTTP endpoint, optional Ollama |
| Deployment and checks | uv, Docker Compose, Caddy, pytest, Ruff, GitHub Actions |

See the [stack study guide](docs/stack.md) for what each piece does and a suggested learning order.

## Verify

After starting the services and applying migrations:

```sh
uv run ruff check .
uv run pytest tests/unit
uv run pytest tests/integration tests/contract tests/e2e
uv run python -m evals.run --suite synthetic --provider stub --output artifacts/eval.json
```

This follows CI's check order after environment setup. Default tests force the stub provider;
Whisper-dependent tests are marked `slow` and excluded by default. Engineering tests and
synthetic evaluations do not establish clinical accuracy.

## Learn more

- [Documentation index](docs/README.md) - guides, architecture and contributor references.
- [Architecture](docs/02-architecture.md) - authorization, ingestion, retrieval and evidence.
- [Evaluation results](docs/evaluation-results.md) - measured results and their limits.
- [Operations](docs/operations.md) - workers, recovery and data lifecycle.

Only synthetic data belongs in this repository. Real-data use requires separate decisions about
source permissions, consent, hosting, provider handling and clinical ownership.
