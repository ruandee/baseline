# Baseline stack study guide

This describes technologies present in the repository. Optional providers and deployment
components do not imply a live service or completed acceptance.

| Area | Technology | What to learn / where it fits |
| --- | --- | --- |
| Browser | HTML, CSS, JavaScript, SVG | Forms, DOM events, fetch, audio capture and charts; no Node build required |
| Motion experiment | MediaPipe Tasks Vision, Web Workers, WebAssembly | Browser pose tracking and derived measurements; video is not uploaded |
| Language | Python 3.12-3.14 | Types, modules, exceptions, async functions and virtual environments |
| HTTP API | FastAPI, Uvicorn | Routes, dependency injection, ASGI and request/response handling |
| Validation | Pydantic, pydantic-settings | Strict schemas, typed settings and environment variables |
| Database | PostgreSQL 17 | SQL, transactions, constraints, indexes and row-level security |
| Time series | TimescaleDB | `time_bucket` aggregation; voice checks remain a plain table for RLS isolation |
| Retrieval | PostgreSQL full-text search, pgvector | Scoped candidate retrieval; current vectors are hashes, not semantic embeddings |
| Database access | Psycopg | Parameterized SQL and transaction-scoped tenant/actor settings |
| Migrations | Alembic, SQLAlchemy | Versioned schema changes; runtime storage primarily uses Psycopg SQL |
| Source objects | S3 API, boto3, LocalStack | Immutable objects and metadata; LocalStack supplies local synthetic S3 |
| Identity | JWT, PyJWT | Signed tokens, roles and patient assignments; synthetic identity only |
| Audio decoding | ffmpeg, SoundFile | Convert browser audio into consistent PCM samples |
| Speech segmentation | WebRTC VAD | Separate voiced runs from pauses |
| Transcription | faster-whisper / Whisper base | Transcript and word timing; not the verdict engine |
| Pitch and arrays | Praat via praat-parselmouth, NumPy | Pitch extraction, sample arrays and feature computation |
| Change detection | Median/MAD, z-scores, EWMA, CUSUM | Personal baselines, drift and repeated-change confirmation; implemented engineering rules |
| Model requests | HTTPX, compatible HTTP provider / Gemini, optional Ollama | Structured context extraction and constrained drafts with validation and fallbacks |
| Background processing | Python leased-job worker | Claims, leases, retries and atomic publication; no Celery or Redis required |
| Safety sessions | KAZE scheduler, optional SMS adapter | Check-in timing, escalation and acknowledgement; default delivery is simulated |
| Packaging | uv, pyproject.toml, uv.lock, Hatchling | Reproducible dependency installation and Python packaging |
| Deployment | Docker, Docker Compose, Caddy | Services, health checks, reverse proxy and HTTPS |
| Verification | pytest, Ruff, GitHub Actions | Unit/integration/contract/end-to-end checks, lint and CI |

## Suggested study order

1. **Python and HTTP basics.** Follow a request from a browser `fetch` call into a FastAPI route.
2. **Pydantic and SQL.** Learn how input is validated and how PostgreSQL stores related records.
3. **Authorization and transactions.** Read `auth.py`, `storage.py` and the RLS tests together.
4. **The evidence flow.** Trace `ingestion.py` - `worker.py` - `extraction.py` - `retrieval.py`.
5. **Audio and statistics.** Follow a voice check through `src/patient_memory/baseline/` and
   distinguish measured features, change status and rule-selected verdicts.
6. **Model boundaries.** Read `providers.py` and `generation.py`, then the context/SBAR decisions.
7. **Operations.** Run the deterministic tests, inspect Compose, then learn migrations and Caddy.

Start with the [architecture](02-architecture.md) and use [runtime status](build-status.md)
to distinguish implemented engineering behavior from remaining validation.
