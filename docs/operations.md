# Synthetic operations and handoff

## Services and scope

The API and worker run as host Python processes. Compose runs PostgreSQL 17 with TimescaleDB and pgvector (the `timescaledb-ha` image, volume `pgdata_timescale`) and LocalStack S3, with pinned image digests. See [decision 004](decisions/004-timescale.md). MinIO was replaced after its image was unavailable. Services bind to loopback. `PM_ENVIRONMENT` must be `synthetic`; other environments fail validation.

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

KAZE safety sessions (decision 018) are deleted 24 h after they end by `pm_retire_safety_sessions()`, together with their checks, locations, assessments, contacts, escalation events and arm idempotency snapshot. Run the worker for the `kaze-demo` tenant as the `kaze-service` principal (`python -m scripts.kaze_demo` prints both IDs); it calls retention at most once a minute. Migrations must run as a superuser or BYPASSRLS role (`PM_ADMIN_DATABASE_URL`): migration 006 refuses otherwise, because its SECURITY DEFINER functions (`pm_safety_tenant`, `pm_acknowledge_escalation`, `pm_retire_safety_sessions`) rely on their owner bypassing forced RLS and scope rows themselves. Do not reassign their ownership to an RLS-bound role.

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

## Local toolchain on macOS

`docker compose` needs a container engine. With Homebrew: `brew install colima docker-compose`,
add `"cliPluginsExtraDirs": ["/opt/homebrew/lib/docker/cli-plugins"]` to `~/.docker/config.json`,
then `colima start`. Agent shells may lack Homebrew on `PATH`; prefix commands with
`export PATH=/opt/homebrew/bin:$HOME/.local/bin:$PATH`.

The Colima VM clock drifts after sleep or restart. Tests compare host time with database time and
stop at startup when the database clock is more than 10 ms ahead. Set it slightly behind the host:

```sh
colima ssh -- sudo date -u -s "@$(python3 -c 'import time;print("%.3f"%(time.time()+0.3))')"
```

## Golden clips (BL-06)

`tests/unit/test_golden_clips.py` runs four real recordings of the fixed prompt through the production
pipeline with real Whisper: `normal`, `slow`, `pausey` and `stairs`. The audio stays out of Git
(`data/raw/` is ignored), and CI skips the tests because they are marked `slow`. Until all four
exist the module skips and says which are missing.

```sh
mkdir -p data/raw/golden
ffmpeg -hide_banner -f avfoundation -list_devices true -i "" 2>&1 | grep -A9 "audio devices"
ffmpeg -hide_banner -y -f avfoundation -i ":<mic index>" -t 25 -ac 1 data/raw/golden/normal.wav
uv run pytest -m slow tests/unit/test_golden_clips.py -v -rA
```

Use the same microphone for all four, and pick it from the list: on this Mac index 0 is "Microsoft
Teams Audio", not the microphone. Say "Count from one to twenty, then say the days of the week,
starting with Monday." each time: `slow` at about two thirds of the normal pace, `pausey` with a
stop of about a second after every fourth number and between the days, `stairs` straight after
climbing stairs. Press `q` when you finish the days: the command allows up to 25 s because a slow or
pausey take can run past 15 s. Core browser capture now permits 30 s (decision 030), and the pipeline refuses anything over 30 s.
Keep one file per name (the test fails with a clear message on a stale second take). If a real clip fails the quality gate
or the direction check, the test prints the measured features: report them rather than loosening
the thresholds. Decision 030 revises the stairs expectation to exploratory: its measurements are
reported without requiring a pitch rise. The original 3-pass/1-fail result is preserved there.
All four clips still need to pass quality. For Dee's API enrollment and live demo, follow
[live-voice-demo.md](live-voice-demo.md); enrollment requires five distinct rested recordings.

## Current limits

- Free-text notes remain attributed source assertions with uncertain status. No validated clinical entity extraction or free-text contradiction classifier is implemented.
- Structured conflicts, intervals, amendments, explicit order-stop links and patient attribution work; free-text semantics still need review.
- Full-text ranking is combined with deterministic 64-dimensional hash vectors. Hash vectors are test plumbing, not semantic synonym search. Real model embeddings need a versioned adapter/index migration.
- Evidence is capped at 12 spans and 6,000 UTF-8 bytes; this is not exact tokenizer accounting. Truncation is visible.
- The optional LLM selects evidence; server code returns exact cited quotations and preserves structured contradictions/order-stop evidence. Diagnostic advice and unverified paraphrases are outside this prototype.
- Tests do not establish clinical usefulness, independent human support review, two-model clinical comparison or 10k-note performance.
