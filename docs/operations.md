# Synthetic operations and handoff

## Services and scope

The API and worker run as host Python processes. Compose runs PostgreSQL+pgvector and LocalStack S3 with pinned image digests. MinIO was replaced after its image was unavailable. Services bind to loopback. `PM_ENVIRONMENT` must be `synthetic`; other environments fail validation.

`PM_ADMIN_DATABASE_URL` is for migrations, fixture bootstrap and evaluation. API and worker queries use `PM_DATABASE_URL`, a non-owner role without BYPASSRLS. An approved deployment must give runtime processes only runtime credentials, with a separate migration identity. Checked-in passwords are local fictional-data credentials.

## Worker and recovery

The fixture loader prints synthetic patient IDs, tenant/actor IDs and short-lived bearer tokens. Run a worker for each tenant/importer scope:

```powershell
uv run python -m patient_memory.worker --tenant <tenant-uuid> --actor <importer-uuid>
```

Workers cannot read unassigned patients. Leases last 60 seconds. Transient failures back off and stop after five failed attempts; invalid hashes/extraction fail immediately. Retry failed jobs through the authenticated retry endpoint with an idempotency key. Restarting workers reclaims expired leases. Raw bytes are hash-verified and publication is transactional. Demo and fixture scripts process their own jobs inline.

Import a correction as a new version referencing `supersedes_version_id` and preserving the logical document ID. `as_of` is the event horizon; `known_at` is the evidence availability cutoff. Replaying the same extractor preserves publication time and stable span IDs.

## Permissions and deletion

Importers can retract or change source visibility, bumping revision and invalidating answers. Assignment changes require a tenant administrator. Administrative patient metadata access does not grant note access. Queries recheck assignment and revision after generation.

`POST .../sources/{id}/purge` immediately retracts a source and queues erasure. A worker deletes its S3 object, facts, embeddings, relationships and cached answers, then clears payload/canonical text. Failed object deletion retries after 30 seconds. Non-content IDs, hashes, job state and audit metadata remain. Earlier backups are outside active-store purge: an actual pilot needs a backup expiry/deletion policy.

## Repair and reconciliation

```powershell
uv run python -m scripts.maintenance reindex --tenant <uuid> --actor <uuid> --patient <uuid>
uv run python -m scripts.maintenance orphan-report --tenant <uuid> --actor <uuid> --patient <uuid>
```

Reindex queues completed/failed active sources for the same deterministic extractor. Run the worker afterward. Published evidence remains available while the job is replayed; stable span IDs avoid duplicates. A new extractor schema/version needs a migration, not this repair command.

Orphan reconciliation checks only an assigned patient's object prefix, unreferenced objects older than 24 hours, and holds the patient ingestion lock while checking. `orphan-delete` applies those rules and removes the candidates. Do not use it to clean arbitrary storage paths.

## Inspection and backups

Liveness is public. Readiness requires an administrator and checks DB plus source bucket. Job endpoints show stages, attempts and sanitized failures. Application logs contain route templates, status and duration. Start Uvicorn with `--no-access-log` to avoid raw URL query strings in access logs. Audit records omit note bodies/questions; inspect them using an operations identity, not the runtime role.

Back up PostgreSQL with `pg_dump -Fc` to a file inside the DB container, then copy it out with `docker compose cp`. Avoid PowerShell text redirection of binary archives. Export S3 objects separately at the same paused-writer boundary. Restore into an isolated Compose project/ports, run migrations forward, verify source hashes and run a demo before switching clients. Migrations refuse destructive downgrade.

LocalStack is a development emulator. Validate persistence in your installed edition and export objects before container replacement; a volume alone is not a backup guarantee. A durable pilot object-store choice remains a deployment decision.

## Current limits

- Free-text notes remain attributed source assertions with uncertain status. No validated clinical entity extraction or free-text contradiction classifier is implemented.
- Structured conflicts, intervals, amendments, explicit order-stop links and patient attribution work; free-text semantics still need review.
- Full-text ranking is combined with deterministic 64-dimensional hash vectors. Hash vectors are test plumbing, not semantic synonym search. Real model embeddings need a versioned adapter/index migration.
- Evidence is capped at 12 spans and 6,000 UTF-8 bytes; this is not exact tokenizer accounting. Truncation is visible.
- The optional LLM selects evidence; server code returns exact cited quotations and preserves structured contradictions/order-stop evidence. Diagnostic advice and unverified paraphrases are outside this prototype.
- Tests do not establish clinical usefulness, independent human support review, two-model clinical comparison or 10k-note performance.
