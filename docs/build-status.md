# Implementation review handoff

## BL-10 — Note context extraction

Bounded schema provider client, exact-quote note tagging and deterministic keyword fallback
now run atomically with worker publication. Importers can process legacy/unprocessed notes
through `POST /v1/patients/{id}/notes/extract`, one per batch; optional `retry_fallback=true`
explicitly retries keyword results. Migration 005 adds forced-RLS completion markers so empty
results are idempotent. Notes retain uncertain source attribution and existing fact IDs.
OpenAPI is regenerated. See [decision 013](decisions/013-note-context-extraction.md).
Provider work runs outside database transactions/locks, under a cancellable combined
15-second HTTP deadline; publication rechecks authorization, source state and revision.
Contracted negation and negated poor-sleep propositions abstain conservatively.
After integrating reviewed BL-11/13 changes, local frozen sync/lint pass; unit tests
222 passed with ffmpeg, no skips, 6 slow deselections.
DB-backed migration/contract/integration tests and stub evaluation await CI; no live model
calls were made. This is conservative engineering validation, not clinical validation.

Implemented on `build/backend-mvp` with separate commits. Read this alongside the original target specification; implementation does not imply all research/pilot gates are met.

| Milestone | Implemented behavior | Remaining scope or gate |
| --- | --- | --- |
| B01 | Locked Python project, Compose, CI checks | Windows local and CI Linux validation recorded separately |
| B02 | Pydantic contracts, bearer JWT validation, membership/assignment checks, error envelope, generated OpenAPI | Production identity is deliberately disabled |
| B03 | Composite constraints, forced RLS, non-owner runtime, two-tenant fixtures | Actual clinical identity/source mapping deferred |
| B04 | Immutable S3 objects, idempotency, leased jobs, retry/backoff, atomic publication | Production queue/load operations not validated |
| B05 | Exact Unicode spans, structured facts, intervals, relationships, conservative note assertions | No validated clinical free-text extractor or semantic conflict resolution |
| B06 | Patient/time-scoped full-text/hash-vector fusion, timeline, conflict/order evidence expansion | Real semantic embeddings and model-specific tokenizer budget remain future work |
| B07 | Questions/summaries, exact citations, unknowns/conflicts, provider/schema failures | Summary is an evidence selection, not free-form clinical prose |
| B08 | Permission/revision rechecks, scoped cache, shared rate limits, audit, retraction/visibility/purge | Pilot retention/backup expiry policy remains undecided |
| B09 | E01Ã¢â‚¬â€œE20 engineering cases and 60-question synthetic regression runner | Clinical/human support gates and untouched model test set remain unmet |
| B10 | Optional compatible HTTP adapter and native Ollama structured selection | Live local Qwen3.5 trial documented in local-model-results.md; two-model quality comparison remains unrun |
| B11 | Runnable HTTP demo, longitudinal loader, repair/reconciliation tools, operations guide | Real-data pilot and hospital integration require separate decisions |

The latest full local suite at this point passed 42 tests, including actual PostgreSQL/S3 integration; lint passed. The 60-question offline regression returned expected-source recall 48/48, correct abstention 12/12 and in-scope retrieval 60/60. Human support review is explicitly unmeasured. The first benchmark exposed a false relevance match; its failure is preserved in `docs/evaluation-results.md`.

To reproduce, follow README from a clean clone, then run the tests/evaluation and demo. Optional live-model calls are not run by ordinary tests or CI. Review the changed behavior and limits before approving a pilot; no deployment has been performed.

## F01 — Local patient workspace

Added a local-only frontend extension after B11: fictional patient roster, timeline
filters, cited questions, evidence inspection and UTC shift handovers. Launch with
`uv run python -m scripts.frontend` and open <http://127.0.0.1:8001>. Browser sessions
use a read-only nurse account. No production API/schema changes. Full suite: 44
passed; lint and JavaScript syntax checks pass. See
[decision 003](decisions/003-local-patient-workspace.md) for boundaries and rationale.

## BL-16 — Baseline frontend scaffold

`frontend/baseline.html`, `baseline.js` and `baseline.css` give the Baseline pages a shared
shell: routes `/unit`, `/resident/{id}` and `/check` (page bodies arrive with BL-18, BL-19 and
BL-17), verdict colour tokens and an API check (liveness plus a nurse-token patient read; `/v1/health/ready` is administrator-only). Opt-in hosted mode
(`PM_FRONTEND_HOSTS`, `PM_DEMO_TOKEN`) lets a phone reach it over HTTPS. See
[decision 005](decisions/005-baseline-frontend-location.md). Contract tests were added in
`tests/contract/test_frontend.py`; they need the database services.

## BL-01 — Demo env hardening

Added configurable token TTL (48-hour default), demo rate-limit and Gemini-compatible
environment entries, plus `scripts/gemini_smoke.py` with strict schema validation.
The smoke call is opt-in and requires a user-supplied key; no provider call ran in
CI. Unit tests pass (44 passed, 2 skipped, 2 deselected) and lint passes. See
[decision 009](decisions/009-demo-env-and-gemini-smoke.md).

## BL-08 — Pure change engine

`baseline.engine.evaluate` computes enrolled/rolling baseline scores, EWMA, CUSUM
and change status without storage or API integration. Its six configuration values
reject nonfinite or invalid ranges at startup. Threshold interpretation and unchanged
single-clip CUSUM behavior are recorded in
[decision 011](decisions/011-change-engine-interpretation.md).

Review revision: lint passed; unit tests returned 93 passed, 7 skipped (ffmpeg is
unavailable), and 2 slow tests deselected on Windows/Python 3.14. Database-backed
integration/contract/e2e checks, migrations and stub evaluation were not rerun because
Docker is unavailable locally. API/verdict integration belongs to BL-11.

## BL-07 — Voice check upload

`POST /v1/patients/{id}/checks` takes `multipart/form-data` (`audio`, `mode`, `device_id`, optional
`device_ts` and `is_baseline`), runs normalize, VAD, ASR, prosody and the quality gate
(`speech/pipeline.py`) and stores the row in `voice_checks`, unusable clips included. Only care-team
roles (`nurse`, `importer`) may write; anyone else, and any other patient, gets 404 before the audio
is touched. `PayloadLimit` accepts multipart on this one route only, and its 2 MB cap still applies
to the whole body, so the audio itself must be a little under 2 MB. Temp audio is deleted in a
`finally` unless `PM_KEEP_AUDIO=true`. Whisper loads at startup; a load failure is logged and retried
on the first check rather than stopping the API.

Not done here: `change` and `assessment` are `null` and `timings_ms` has no `engine` or `verdict`
keys until the change engine (BL-08) and the verdict table (BL-11) exist. Clips over 30 s are
refused (the prompt stops at 15 s) so a crafted upload cannot hold Whisper for minutes. The
p95 under 5 s target has not been measured on the demo host.


BL-01 takeover update: main conflicts resolved; token TTL tested at 1, 7, 48 and
72 hours with expired-token rejection; provider error/schema/model-discovery tests
added. Local lint and frozen sync pass; unit suite 68 passed, 7 ffmpeg-dependent
skips and 2 slow deselections. Previous live Gemini request returned HTTP 404;
no saved key is available for a retry, so provider acceptance remains open.
See decision 009 for recovery commands and the explicit unrun service checks.

## BL-09 — Structured context and `POST /context`

`baseline/context.py` holds the no-model rules: an `ordered` or `administered` medication event for
a high-risk drug becomes `high_risk_med_new`, `temperature_c` of 37.8 or more becomes
`fever_documented`, and a `context.<tag>` observation becomes that tag. The worker writes the tags
in the same transaction that publishes the facts, quoting the record's own span.
`POST /v1/patients/{id}/context` submits such an observation through normal ingestion and returns
the tag with canonical text and fact published atomically, completing the queued job and bumping
the patient revision once. Its citation resolves immediately without a worker. Generic context
inputs reject check-only `language_change`; structured extraction skips it until check-linked
metadata exists. Migration 004 lets purge delete tags so a purged source leaves no quote behind. See
[decision 007](decisions/007-structured-context-tags.md).

Not done here: Gemini free-text tags, and readers ignoring tags of retracted sources (verdict and
overview tickets must do that join). Only importer-assigned callers can post context, because it
goes through source ingestion.

## Verdicts, assessments and the two read endpoints (BL-11, BL-13)

Every usable check is scored when it is stored and gets an `assessments` row, returned as `change`
and `assessment` by `POST /checks`. `baseline/verdict.py` is the pure verdict table plus the shift
escalation budget (`PM_ESCALATION_BUDGET`, default 3 per 8-hour shift), the no-escalate list
(`PM_NO_ESCALATE_PATIENTS`) and the template SBAR. `GET /v1/watchlist` and
`GET /v1/patients/{id}/overview?days=30` read the stored rows; both are care-team only and apply
RLS. See [decision 012](decisions/012-verdict-assessments-and-overview.md).

Not done: Gemini note extraction and SBAR drafting (BL-10, BL-12), the cohort loader (BL-14), and
the "temperature documented normal" reader. The ffmpeg-dependent contract tests in
`tests/contract/test_checks.py` skip where ffmpeg is not installed, so the audio path into
`store_check` is covered only by `tests/integration/test_assessments.py`, which calls it directly.


## BL-11/BL-13 review corrections

A review branch adds source revision/provenance to assessments, atomically scrubs copied quotes/SBAR
on source revision bumps, and withholds stale assessments on both read endpoints. Active context
excludes superseded sources. History selection preserves enrolled clips and prompt scope, and
advisory locks serialize concurrent budget/history decisions with access rechecks. Browser upload
contracts now require the built assessment response and CI installs ffmpeg. See
[decision 015](decisions/015-assessment-evidence-lifecycle.md).

Local Windows/Python 3.14 with ffmpeg: lint passed; unit 150 passed, 6 slow deselected. Service-backed
regressions require PostgreSQL/S3, unavailable locally; CI results are reported on the review PR.

## BL-12 ? Validated SBAR drafts (integration pending)



Watch/escalate checks now draft through `baseline.sbar` after deterministic verdict selection.

Configured providers receive only rounded feature values and selected context; all S/B/A/R

sections, allowed IDs/numbers, banned phrases and the fixed action label are validated. Provider

or validation failure uses the template, and stub mode never calls a provider. Canonical check/tag

IDs are validated before mapping to the existing UI check/fact citation convention. See

[decision 014](decisions/014-validated-sbar-drafts.md).



Local Windows/Python 3.14 verification: frozen sync and lint pass; 169 unit tests pass with FFmpeg

on PATH, 6 slow tests deselected. DB persistence/authorization tests were added but not run locally

because Docker is unavailable. Migrations, DB-backed suites and stub evaluation await CI. No live

model call or real-audio validation was performed. This branch depends on BL-10's shared client

and BL-11/13 review integration, including stored evidence invalidation on lifecycle changes;

BL-12 remains open until those dependencies and full CI pass.



BL-12 semantic review hardening: model output must exactly match server-constructed supported

sentence/evidence pairs, and R must be the fixed standard action sentence with no extra advice.

This closes the unsupported-negative and appended-treatment gaps left by IDs/numbers-only

validation. Tests reject invented absence/presence, swapped numbers, wrong tag attribution and

additional action clauses. This is constrained sentence assembly, not unrestricted prose generation;

ADR 014 records the design change and remaining clinical/evidence validity limits.





BL-12 integration follow-up: the check transaction commits its deterministic verdict, budget slot
and template before provider drafting. Enrichment runs outside database transactions, then
publishes only after care-team, source-revision and check-eligibility rechecks. Source changes
return 409 `memory_changed` with the original check preserved; revoked access returns 404. See
ADR 014. Local lint and ffmpeg-enabled unit suite: 250 passed, 6 slow deselected. New concurrency
and lifecycle regressions require the service-backed CI run.

## BL-08 ? Accepted corroborated change policy

The user explicitly approved PR #60 and paired Mr. T scenario PR #61. The accepted
`multifeature-cusum-v2` policy supersedes decision011's single-feature-CUSUM interpretation.
Instantaneous confirmation requires corresponding feature names and pitch direction on both
checks within24h. CUSUM needs two ongoing supported features; the same features/direction must
persist on the preceding usable check to confirm. Pitch has separate signed streams; a lone
feature or recovered residual accumulation is diagnostic only. Thresholds and baseline rules
are unchanged. See [decision019](decisions/019-multifeature-cusum-proposal.md).

Latest main (including BL-10 and reviewed BL-12) is integrated. All720 original/amended replay
checks used the actual engine, deterministic source context and verdict rules: original20%
Mr. T scenario matches11/12 declared snapshots; approved35% matches12/12 (K escalate, T explained,
L watch/recheck1h). Both datasets have zero flags across all270 control checks and the expected
recovery. This is engineering fixture evidence, not clinical validation. Latest local lint and
269 unit tests pass with FFmpeg;6 slow tests deselected. Full integrated CI still precedes merge.
No live model or real-audio calls were made; loader/presentation acceptance is tracked separately.

## BL-14 ? Scoped loader and explicit historical presentations

`scripts.load_baseline_demo` provisions twelve known synthetic residents, publishes immutable
SourceInput records and shared BL-10 note context BEFORE runtime-role scoring, and verifies exact
source/fact/tag support. Existing source identities/versions/payload hashes must match the full
manifest; synthetic system stamps alone never authorize extra context. Revoked assignments stay
revoked. Immutable authored checks retain synthetic/non-audio provenance, no transcript/words.
Unchanged checks and source-revision/signature-matching assessments are reused on rerun.

Explicit all-history loads360 rows; scenario-snapshots loads353 prefixes (K/Tthroughday27,
Lthroughday29, controlsday30). The report distinguishes retrospective event-time/current-knowledge
replay from a shared/current-time unit. Fuller histories cannot be destructively truncated.
Expected/actual snapshot and latest results are reported strictly; mismatches return nonzero.
The nurse token/roster are written only to ignored artifacts, never stdout or Git.

Approved policy#60 is integrated; original +20% Mr. T fixture remains here until separately
reviewable approved scenario#61 adoption. Mr. T is the sole remaining declared-snapshot mismatch;
K escalates, L watches/rechecks1h and controls remain quiet. Configured loader scoring deliberately
stores the service template instead of issuing hundreds of historical SBAR model calls. Offline
mode uses no provider calls. See decision008 and the fixture README for commands/integration.

Latest integrated local lint/unit:289 passed withFFmpeg,6 slow deselected. Previous loader CI
head2023ec7 passed242 unit/119 DB cases withzero skips; new combined-head fullCI is pending.
Six loader DB cases cover idempotency, publication/evidence support, prefix/full history,
RLS/revocation and injected context. Local Docker/DB/migrations/eval remain unrun. BL-14 remains
open for accepted scenario adoption, final strict DB acceptance and current-time/readback wiring.
Real-audio/runner, hosting/reset and normal-temperature display are separate outstanding gates.

## BL-25 — KAZE safety sessions (model and endpoints)

Migration 006 (chained off 005) adds `tenants.safety_mode`, `safety_sessions`, `safety_contacts`
and `escalation_events` (forced RLS, composite tenant/patient and session-scoped FKs), plus
`session_id`, `lat`, `lon`, `accuracy_m` on `voice_checks`. Sessions exist only in safety-mode
tenants (`scripts/kaze_demo.py` creates `kaze-demo`); the person is importer on their own row,
the `kaze-service` principal is nurse. Endpoints: arm (`POST /v1/patients/{id}/sessions`), list,
status and end. `POST /checks` accepts `session_id` and location; the third usable baseline
clip activates the session, and session checks are scored only against that session's history.
`pm_acknowledge_escalation` (hashed token, for BL-27) and `pm_retire_safety_sessions` (expiry and
24 h deletion of session checks/locations/assessments/contacts/events; worker calls it each
minute) are SECURITY DEFINER and tenant-scoped. Contract: [decision 018](decisions/018-kaze-session-model.md).

Not done: scheduler/ladder progression and check-in resets (BL-26), SMS sender and `/ack` route
(BL-27), pages (BL-28), `loud_venue` quality tolerance, two-phone acceptance, and integrated
acceptance after the PointClickCare path reaches BL-13. DB-backed tests run in CI only (no
local Docker).
