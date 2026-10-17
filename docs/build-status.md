# Implementation review handoff

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

## BL-32 — Mock Vox encounter adapter

`POST /v1/integrations/vox/encounters` (multipart, the second and last multipart route) is a
**mock** Vox Advantage adapter; it is not a PointClickCare or Vox integration, and every response
says `mock: true`. After the care-team gate (404 for other tenants, unassigned patients and
non-care roles, before consent or audio work), consent must be the literal `true`, else 422
`consent_required` with a committed `vox_encounter/consent_refused` audit row and nothing stored.
Resident segments, minus any staff/other overlap, are cut from one bounded decode (encounter at
most 120 s, analysis at most 60 s) and stored through `store_check` as `mode=resident`,
`prompt_version=free-conversation-v1`, `device_id=vox-mock`. Under 8 s of resident speech gives
`too_little_resident_speech` without transcription. Free conversation skips only the on-script
quality reason and is scored with `PM_Z_THRESHOLD_FREE` (2.5) against its own prompt's history.
The overview charts the latest assessment's prompt (`baseline.prompt_version`) and the watch-list
sparkline the counting prompt. Fixture: `fixtures/synthetic/vox_encounter_mrs_k.json` (no audio).
See [decision 016](decisions/016-vox-mock-encounter-adapter.md).

Not done: any Vox UI or mock label on a page, real-speech validation (recordings on hold; tests use
synthetic tones on the fixture timeline), and the BL-33 note export. No migration.
