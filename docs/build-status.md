# Implementation status and remaining gates

This is the current runtime handoff after the explicitly approved policy/scenario adoption
(PRs #60 and #61), built on the backend MVP and reviewed Baseline core. Implementation and
synthetic engineering checks do not establish clinical validation or real-data pilot readiness.
The final integrated commit's CI is authoritative; historical validation counts are not a claim
that a new host, recording, provider or frontend flow has been verified.

## Original backend MVP

| Milestone | Implemented behavior | Remaining scope or gate |
| --- | --- | --- |
| B01 | Locked Python project, Compose and CI | Host/toolchain acceptance remains environment-specific |
| B02 | Strict contracts, synthetic JWT identity, assignment checks and OpenAPI | Production identity disabled |
| B03 | Composite tenant/patient constraints, forced RLS and non-owner runtime | Real identity/source mapping deferred |
| B04 | Immutable S3 sources, idempotency, leased jobs and atomic publication | Production queue/load operations unvalidated |
| B05 | Exact Unicode evidence, structured facts, intervals and attribution | No clinically validated free-text extractor or semantic conflict resolution |
| B06 | Scoped full-text/hash-vector retrieval and temporal/evidence expansion | Real semantic embeddings and model-specific token budget remain future work |
| B07 | Cited answers/summaries and explicit unknown/conflict/provider failures | Original summaries select evidence; no clinical prose validation |
| B08 | Scoped caches, limits, audit, retraction/visibility/purge and revision checks | Pilot retention/backup expiry policy undecided |
| B09 | E01-E20 engineering cases and frozen synthetic regression runner | Clinical/human support and untouched-model gates unmet |
| B10 | Compatible HTTP and native Ollama adapters | Two-model quality comparison unrun; earlier local trial is in local-model-results.md |
| B11 | HTTP demo, longitudinal fixtures, repair tools and operations guide | Real-data pilot and hospital integration need separate decisions |

The original benchmark's denominators and preserved false-relevance failure remain in
[evaluation-results.md](evaluation-results.md). Human support review is unmeasured. Ordinary
CI uses deterministic stubs and synthetic data; optional provider calls are not CI acceptance.
No real-data integration is authorized by these implemented milestones.

## Baseline runtime

| Area | Current behavior | Evidence / remaining gate |
| --- | --- | --- |
| BL-01 environment | Configurable positive token TTL (48-hour default), demo configuration, strict Gemini smoke/model discovery | [Decision 009](decisions/009-demo-env-and-gemini-smoke.md); nondefault TTL/expiry cases tested |
| BL-03 storage | Voice checks, context and assessments under forced RLS; ordinary voice table with Timescale time_bucket | [Decision 004](decisions/004-timescale.md); runtime-role isolation tested |
| BL-04/05/07 speech checks | Multipart upload, normalize/VAD/ASR/prosody/quality, immutable check/audit storage and usable-check assessment | [Decision 006](decisions/006-voice-check-upload.md); real audio and host latency remain separate |
| BL-08 change engine | Accepted multifeature-cusum-v2, enrolled/rolling calibration, robust scores and diagnostic trends | [Decision 019](decisions/019-multifeature-cusum-proposal.md), superseding decision 011 status interpretation |
| BL-09 structured context | Atomic canonical source/fact/tag publication, immediately resolvable evidence and structured medication/vital rules | [Decision 007](decisions/007-structured-context-tags.md); importer-only writes, generic check-only language_change rejected |
| BL-10 note context | Exact quoted note tags, conservative keyword fallback and on-demand legacy extraction | [Decision 013](decisions/013-note-context-extraction.md); migration005 and worker publication integrated |
| BL-11/13 verdict/read models | Deterministic verdict/action, shift budget, runner suppression, watchlist and overview | [Decision 012](decisions/012-verdict-assessments-and-overview.md); actual usable checks return change and assessment |
| Evidence lifecycle | Source revision/provenance, atomic stale quote/SBAR scrubbing, read withholding, supersession and serialized admission | [Decision 015](decisions/015-assessment-evidence-lifecycle.md); authorization rechecked on return/publication |
| BL-12 SBAR | Grounded sentence assembly, exact standard action, strict IDs/numbers/sections, template fallback and post-commit enrichment | [Decision 014](decisions/014-validated-sbar-drafts.md); provider work occurs outside DB transactions |
| BL-14 loader | Twelve deterministic fictional residents, immutable published sources, authored synthetic checks, real runtime-role scoring and strict reports | [Decision 008](decisions/008-baseline-storyline-preparation.md), [loader guide](../fixtures/synthetic/baseline_storylines.README.md); approved +35% Mr. T scenario |
| F01 / BL-16 frontend | Local evidence workspace plus Baseline shell and same-origin session/host guards | [Decision 003](decisions/003-local-patient-workspace.md), [Decision 005](decisions/005-baseline-frontend-location.md); full capture/resident readback needs frontend verification |

Only care-team roles can write voice checks; unauthorized patients/roles return 404 before audio
work. Multipart is allowed only on the check route, with a 2 MB whole-body limit; other routes
remain JSON-only. Upload duration is bounded at 30 s; product capture is 15 s. Temporary audio is
deleted unless PM_KEEP_AUDIO=true. Unusable clips are stored for audit and receive neither
change nor assessment. Usable clips run the actual engine/verdict service and return both.
Whisper startup warming, browser-format contracts and extraction tests are implemented; installing
FFmpeg or passing synthetic audio tests does not establish real-recording quality or host p95.

Enrolled calibration needs at least 3 usable earlier explicitly marked baseline checks. Rolling
calibration uses up to 10 usable checks from 30 days, excluding the latest 12 hours. Same prompt is
required; the same device is preferred when at least 3 matching clips exist. Fewer than 3 baseline
checks returns enrolling. Confirmation requires corresponding feature names and pitch direction
within 24 hours. Pitch CUSUM has separate signed streams; supported multifeature accumulation can
be provisional, with confirmation on a supported repeat. Single-feature or recovered residual
CUSUM is diagnostic only. Thresholds are unchanged and echoed with the accepted policy version.
These are engineering rules, not clinically calibrated thresholds.

Note extraction runs provider work outside locked transactions with a cancellable combined 15 s
HTTP deadline. Publication rechecks scope, source state and revision. On-demand extraction is
importer-only and processes one note per batch; retry_fallback explicitly retries keyword results.
A missing, fabricated, negated or ambiguous quote is dropped conservatively. The model never
chooses a verdict or action and cannot retrieve more records or invoke tools.

SBAR providers may assemble only server-constructed supported sentence/evidence pairs. R is
exactly the fixed standard action sentence; extra advice, unsupported negatives/positives,
misattribution and swapped numeric relationships fall back to the template. The check transaction
commits its verdict and template before optional enrichment. Enrichment then rechecks care-team
access, source revision and check eligibility; a source change returns 409 memory_changed with the
original check preserved, and revoked access returns 404. Generated prose remains a draft for
verification; consistency with supplied data is not clinical truth or completeness.

## Loader acceptance and presentation

The user explicitly approved both the change-policy contract and Mr. T's authored pause-ratio AND
mean-pause increase from 20% to 35% on days 26/27. Speech rate -15%, all other residents, notes, dates,
seed and thresholds remain unchanged. Original versus amended 720-check replays used the actual
engine, structured rules, offline note extraction and verdict table: original inputs match 11/12
declared snapshots (Mr. T is the mismatch); approved inputs match 12/12: K escalate/4at_now,
T explained/none, L watch/recheck_1h and nine within_normal controls. Both datasets have zero
provisional/change flags across all 270 control checks and expected recovery. This authored-fixture
evidence is not statistical false-alarm calibration or clinical validation.

The loader publishes ALL sources/context before ANY assessment, verifies exact supporting spans,
rejects unlisted identities/versions/payload hashes and preserves revoked access. Unchanged runs
reuse immutable checks and source-revision/signature-matching assessments. Every authored check
is synthetic with non-audio provenance, no transcript and no word timestamps. Configured loader
scoring intentionally stores templates instead of making hundreds of historical SBAR model calls;
--offline also forces keyword note extraction and makes no provider requests.

Presentation is explicit: all-history loads 360 checks and reports declared historical snapshots
separately from day 30 recovery. Scenario-snapshots loads 353 prefixes: K/T through
2026-10-14T14:00:00Z, L through 2026-10-16T14:00:00Z and controls through2026-10-17T14:00:00Z.
These are different retrospective event-time cutoffs with currently published evidence, not an
earlier knowledge snapshot or a current-date unit/reset. Fuller histories cannot be silently
truncated. Actual mismatches give a nonzero exit. Report, 12-patient roster and short-lived nurse
token go only to ignored artifacts/baseline-demo; tokens are never printed or committed.

## Validation ledger and external gates

- Manual Gemini 3.5-flash-lite strict schema-connectivity smoke passed twice in this session
  ([BL-01](https://github.com/ruandee/patient-memory-backend/issues/3)). This establishes those
  requests only, not ongoing availability, note/SBAR quality, audio or end-to-end acceptance.
- Reviewed BL-12 CI passed 250 unit and 120 DB-backed tests with no skips. Earlier loader review
  head 2023ec7 passed 242 unit and 119 DB-backed tests with no skips, including real PostgreSQL/S3,
  migrations and stub evaluation. These are historical commit-specific checkpoints.
- Combined approved scenario head01f0733 passes local lint and 289 unit tests with FFmpeg;
  6 slow tests were deselected. Its actual DB test requires all 12 canonical labels/actions,
  idempotency, exact evidence, RLS/revocation and contamination rejection. Final integrated CI
  is tracked on PRs #60/#53/#61; no local Docker/DB run is claimed.
- Real golden recordings, slow Whisper/VAD acceptance and runner baseline/backup/race clips
  remain outstanding. Recordings are on hold. FFmpeg is installed locally; no real audio has
  been validated by the feature loader.
- Public HTTPS/DNS/token configuration, LTE Safari/Chrome capture, warm host p95 below 5 s and
  full UI evidence/SBAR readback remain separate acceptance work.
- Current-time/reset presentation, consuming the full 12-patient roster in hosting/frontend,
  and displaying Mrs. K's documented 37.1 C observation in overview/UI remain outstanding.
- KAZE sessions/SMS/acknowledgement, Vox/experience/export feedback and stretch modalities are
  separate planned features; this handoff does not mark those tickets complete. Submission,
  backup video and two rehearsals are also tracked separately in the build tracker.

Follow README/operations and the exact CI order before claiming a new integrated milestone done.
Do not introduce real patient data before source permissions, hosting, provider handling and
clinical ownership are decided.

## BL-18 live acceptance (Refs #20)

`tests/contract/test_unit_watchlist_live.py` loads the BL-14 cohort (scenario-snapshots,
offline) into a sandbox tenant, reads `/v1/watchlist` through the workspace app and demo token
the page uses, checks that every field `/unit` reads in `frontend/baseline.js` exists in the
live payload, checks the sort contract (Mrs. K escalate, Mrs. L watch, Mr. T explained, nine
within-normal by fused z, the patient with no checks last) and then runs
`tests/js/unit_page.test.mjs` under Node against that captured response. The JS test asserts
rendered order equals API order (no client re-sort), a 10 s interval, no timer or requests
while hidden, an immediate refresh and a new 10 s interval when visible again, and a single
load for a background-opened tab. `tests/unit/test_unit_page_js.py` runs the same JS test on a
committed schema-shaped fixture; both skip only when Node is missing.

Known gap: `scripts.frontend` mints its token for the eval-corpus workspace tenant, while the
loader writes the cohort to `uid("tenant-0")`. A default local `/unit` therefore lists the
workspace patients with no voice checks; it shows the cohort only when `PM_DEMO_TOKEN` is set
to the loader's `artifacts/baseline-demo/session.json` nurse token (BL-21 reset work).

## BL-25 session model integration

Review fixes cover session expiry before capture and after locking, immutable ended-state retention,
24-hour deletion including idempotent arm snapshots, constrained runtime grants, and unconditional
session-audio cleanup. Session-model tests pass locally; final combined service CI remains required.
Scheduler/SMS/pages and the held ADR 018 policy questions remain separate work.


### BL-26/BL-27 branches (pending review)

The stacked scheduler and SMS branches implement the standard KAZE 15-second polling loop,
2.5/5/10/10-minute ladder, raw session change triggers and usable check-in resets. SMS is prepared
inside the locked publication transaction and delivery occurs after commit. Log delivery is the
default; no real text/model/audio call is part of validation. Consent migration 007 remains owned
by BL-31; migration 008 hardens public acknowledgement and durable delivery claims. Dependencies
#27/#28 remain open until reviewed and merged. The six held ADR018 questions remain undecided.


BL-27 adds fixed neutral Twilio/log messages, hash-only token storage, the specified public GET
acknowledgement with minimal HTML, fresh-clock expiry checks and durable at-most-once delivery
claims (migration 008 after consent 007). All sender I/O occurs after commit and lock release.
Timeout/crash uncertainty remains pending, failed steps are not retried, and sent means provider
acceptance only. Default log delivery retains no live tokens/coordinates. Real verified-phone
receipt and public-link acknowledgement acceptance remain unrun; issue #29 must stay open.
