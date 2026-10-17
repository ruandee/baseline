# Patient Memory Backend

Agent-ready build specification for a patient-specific memory service: ingest nursing notes and records, preserve their history and provenance, and return evidence-backed handover summaries and answers.

**Status: synthetic-data backend under implementation.** No clinical validation has been performed.

## Local setup

Prerequisites: Python 3.12–3.14, uv 0.13.1 and Docker Compose v2+. On Windows, `python -m pip install --user uv` installs uv; use `python -m uv` if its executable is outside PATH.

```powershell
uv sync --frozen
docker compose up -d --wait db object-store
uv run alembic upgrade head
uv run pytest tests/unit
```

Compose binds synthetic services to loopback only. The checked-in passwords are synthetic local development credentials. Dependency resolution is captured in `uv.lock`.

## Read and review

1. [Product scope and source](docs/01-product.md): requirements, assumptions, boundaries.
2. [Architecture and data model](docs/02-architecture.md): storage, temporal semantics, ingestion and retrieval.
3. [API and behavior contracts](docs/03-contracts.md): request/response shapes and failure behavior.
4. [Evaluation and data plan](docs/04-evaluation.md): fixtures, metrics and release gates.
5. [Agent implementation plan](docs/05-build-plan.md): dependency-ordered, reviewable implementation commits.
6. [Agent instructions](AGENTS.md): how to execute the plan.

Review the specification commits in order: scope → architecture → contracts → evaluation → agent handoff. Future implementation commits are defined separately in the build plan; they are not claimed as completed work.

## Proposed stack

Python + FastAPI + Pydantic; PostgreSQL with full-text search and pgvector; a separate worker using a PostgreSQL-backed jobs table; S3-compatible source storage. Provider-neutral extraction, embedding and generation interfaces. Pin exact supported versions and image digests in implementation commit B01.

## Start here for agents

Read `AGENTS.md`, then implement B01 only. Proceed through the dependency table in the build plan with one coherent change per commit and recorded verification. Default development uses synthetic fixtures and deterministic model stubs, without credentials or network model calls.

## Decisions still needed before a real pilot

Clinical partner and intended workflow; jurisdiction and hosting; source-system permissions; permitted model provider and data handling; dataset access; consent and retention policy. These do not block synthetic development. No real patient data belongs in this repository.
