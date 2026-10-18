# Implementation status and remaining gates

BL-17 follow-up: live checks display eligible prior baseline checks from the engine contract
and report measured engine/verdict elapsed milliseconds. This does not change scoring policy;
real phone/audio and hosted latency acceptance remain open.

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
| BL-20 hosting (merged #73) | Opt-in `compose.demo.yaml`: ffmpeg image, readiness-gated same-origin API/frontend behind digest-pinned Caddy, tenant-0 worker, explicit migrate/bootstrap/offline BL-14 `load` steps; RLS-read roster (6 seeded, 12 after load); admin URL refused by serve/worker; default JWT secret refused in hosted mode | [Decision 010](decisions/010-demo-hosting.md), [recipe](demo-hosting.md), [beginner walkthrough](deployment-walkthrough.md); CI image smoke on localhost only. No server/domain provisioned; public HTTPS/DNS, phone/LTE capture and host p95 unverified |

Only care-team roles can write voice checks; unauthorized patients/roles return 404 before audio
work. Multipart is allowed only on the check route, with a 2 MB whole-body limit; other routes
remain JSON-only. Upload duration and core `/check` capture are bounded at 30 s (decision 030). Temporary audio is
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
- Dee authorized local golden-recording evaluation: the original suite passed quality, slow-rate
  and deliberate-pause tests but failed the stairs pitch expectation. Decision 030 explicitly
  makes stairs exploratory, preserving that failure. Five distinct API-enrolled rested checks
  and a live readback/rehearsal remain outstanding; the feature loader does not validate real audio.
- Public HTTPS/DNS/token configuration, LTE Safari/Chrome capture and warm host p95 below 5 s
  remain acceptance work. UI evidence/SBAR readback passes API-captured DOM and lifecycle tests;
  physical-phone readback has not been verified.
- The 12-patient roster, Mrs. K's sourced 37.1 C observation, resident charts and preliminary
  export are merged (#55). Current-time reset #79 is merged; hosted timing remains unverified.
- KAZE sessions, scheduler, SMS/acknowledgement and pages are merged (#66/#69/#72/#71/#80);
  hosted worker/bootstrap #76 is merged. Real two-phone SMS/ack acceptance remains open.
  Vox mock and consent/PSW flows are merged; real/nontechnical user acceptance remains open.
  Registry #78 is merged; motion and vitals remain in integration. Submission, backup video and two
  rehearsals are tracked separately; implemented code alone does not close those gates.

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

## Resident / PSW workflow (BL-31)

Migration 007 adds append-only scoped resident/SDM consent and check skips. Unknown, declined,
withdrawn or expired consent blocks capture with audited 403 consent_required before decode/ASR
and is checked again under the patient admission lock. PSWs use score-free due/skip/check receipts;
ordinary PSW transactions cannot retrieve scoring data, records or evidence. Resident capture fixes
pending-permission refusal, uses stable per-mode devices and retains the one-retry/warm-close flow.
See decision 017. Real-browser/nontechnical tester acceptance, additional language protocols and
source-submitter attribution for ?Your observation helped? remain open. This is synthetic only.

KAZE session model, expiry/retention hardening and synthetic engineering tests from decision 018
are integrated. Migration 007 follows 006; explicit synthetic session fixtures record consent.
Scheduler and durable delivery/public acknowledgement are merged; real-device acceptance remains
open. The default sender logs simulated delivery and sends no SMS. Hosted KAZE credentials,
bootstrap and dedicated worker are merged in #76; public-host acceptance remains open.

BL-32 Vox mock adapter integration: care-team authorization, standing `vox_encounter` consent
before decode and locked publication (403 consent_required), plus exactly one raw true request
consent part (422 consent_not_given). Resident-only VAD speech must reach8seconds after the
analysis cap; staff-containing temporary audio is always removed regardless of KEEP_AUDIO.
Checks remain prompt-scoped; first-change marker uses the displayed prompt. Real speech/Vox
UI remain unvalidated, and overview prompt switching stays on hold (decision016).

BL-19 resident integration (merged #55): live authorized overview, four speech charts,
clickable source evidence, server-labelled action handoff button, and structured engine
parameters. Recorded temperature includes source/time (Mrs. K 37.1 Celsius); no absence or
normal-range inference. The available stored SBAR mounts BL-33 exact preliminary export and
local human-edited, unverified preview. API-captured cohort/DOM and lifecycle tests are added;
Exact-head #55 CI passed 419 unit tests (6 optional tests deselected), 239 DB-backed tests,
stub evaluation and image smoke. Real phone/host acceptance remains open. Follow-up #81 keeps
missing current assessments unknown rather than inferring incomplete enrollment.

BL-19 follow-up makes every check citation interactive with matching assessment/check identity
and refreshed authorization. All reason, observation and SBAR citation buttons are exercised,
including withheld readback after assessment change/revocation. Headless Chrome renders desktop
and phone-width synthetic fixtures; this does not claim physical-phone or live-audio acceptance.

BL-28 pages add separate KAZE bootstrap, arming, baseline/session recording, countdown/reminders
and a delivery/acknowledgement timeline. Logged/failed attempts never claim sent SMS. Latest
SMS integration preserves public acknowledgement navigation and clinical/bootstrap guards.
Physical phone/SMS/rehearsal gates remain open; page setup is in docs/kaze-pages.md.

BL-25 loud-venue follow-up scopes the specified 3 dB SNR tolerance to authorized stored session
context and adds the open-session quiet-place hint. All other quality gates remain unchanged;
synthetic checks do not establish real venue or golden-recording acceptance.

Hosted KAZE integration (BL-26 / decision026) adds a separate runtime-role safety worker,
explicit contact-free bootstrap and private safety-person credentials. Consent remains unknown
unless explicitly granted for fixtures; existing withdrawals remain preserved. Public-phone and
real-SMS acceptance remain open.

BL-30 registry (merged #78) adds scoped modalities, explicit missing/stale states, corroboration and
legacy speech compatibility. New captures reproject eligible immutable modalities at current
revision without restoring invalidated decisions; first-change markers reject stale/session
snapshots. Only speech is registered in this base. Decision025/migration010 track the contract;
final exact-head CI remains authoritative after hosting/status integration.

BL-21 reset (merged #79): fixture-only current-time reset verifies all twelve
canonical outcomes, preserves unrelated recordings/consent, refreshes private nurse/PSW/KAZE
credentials and configures runner suppression. Hosted reset under one minute remains unverified.

BL-31 resident counting profiles (decision031/migration014, following013): assigned care staff
explicitly configure a nullable given name and preferred locale using `GET/PUT
/v1/patients/{id}/check-profile`. Only exact `en` maps to the existing English
`count20-days-v1` protocol. Missing/unsupported profiles block counting before decode and
appear as a score-free language-setup state on the PSW due list/direct check page; no English
fallback or roster-name guessing occurs. Admission rejects profile-version changes during
processing and appends a protocol snapshot without rewriting historical checks or fixture hashes.
Known fixture loaders explicitly seed English with no inferred given name, preserving existing
choices. Volunteer capture people remain unconfigured until the care team deliberately sends,
for example, `{"preferred_locale":"en","first_name":"Mary Ann"}` to that endpoint; this
does not grant consent. KAZE session and Vox free-conversation contracts remain unchanged.
Nurse live/runner capture pages provide explicit profile and standing voice-permission forms,
so setup needs no terminal. Permission requires the actual decision, decision maker, confirmation
and SDM reference when applicable. Missing/withdrawn permission keeps Record disabled; the PSW
view receives no setup form or SDM details.
Beginning any setup mutation immediately clears readiness and invalidates microphone/recorder
callbacks; stale preflight reads cannot re-enable capture during a pending write. A fresh tap
is required after setup returns ready. Resident microphone attempts and both resident/nurse
uploads, resends and automatic retries recheck current effective consent and profile; PSWs use
only the score-free consent-state field in the existing profile projection.
Phone screenshots use synthetic loopback responses with no microphone access; real-device,
golden-recording and clinical acceptance gates remain open.
BL-34 motion integration (pending main CI): local-only camera/pose processing uses pinned
self-hosted assets and uploads bounded client-derived measurements with unknown-by-default
motion consent. Final migration011 guards require explicit scoring authorization, including
unset-context denial. Exact source provenance, RLS, purge and projection tests passed on the
feature head; real Chrome model startup/failure used no camera or remote requests. Physical
phone/camera and three measurements in under15seconds remain unverified (Refs #36).

BL-06/15/17 live demo revision (decision 030): Dee replaces the remote caller; core browser
capture permits 30 seconds with manual Stop and the unchanged 30-second server/2 MB body caps.
The API-only enrollment helper requires five distinct rested takes, current care-team access and
recorded consent; it preserves receipts and never automatically retries a POST. It does not
override consent withdrawals. On-stage live mode uses the enrolled capture patient/device to
show measurements; runner mode remains a receipt view. Breathlessness is deferred. Three golden
acceptance gates remain; stairs is a quality-checked exploratory report. Actual enrollment and
physical browser/host/rehearsal acceptance are not claimed by implementation or synthetic CI.

Local revision validation: lint and 578 unit tests passed (five optional slow tests deselected),
plus the revised three-test real Whisper golden suite passed on Dee's original four recordings.
The original stairs pitch failure remains in decision 030. Local Compose cannot connect to the
Docker engine while Windows activation/restart is pending; full service acceptance uses CI and
does not establish that a particular live deployment or phone has passed rehearsal.

Latest live-demo handoff: actual enrollment is paused in this agent and delegated to a teammate.
An optional fixed-outcome presentation is documented as a labelled simulation plan only; no
hardcoded verdict or write into real capture history is implemented.
BL-35 integration: explicit resting HR/RR observations feed current-revision signal projections
and isolated synthetic RR-rise acceptance; unknown rest/time/units stay unavailable. ADR028
records engineering-only vitals parameters and012scoped PSW facts; ordinary evidence remains
denied. Final motion011 from main is preserved unchanged. Speech/canonical cohort unchanged.

BL-12/BL-33 follow-up (ADR029): deterministic multimodal watch/escalate drafts and preliminary
export use exact current/baseline evidence, actual event times, declared labels/units, current
context and existing actions. Source lifecycle/expiry and permissions are rechecked on readback.
Motion remains explicitly client-derived/unverified; missing provenance withholds the whole draft.
No model, threshold/action policy change, clinical sign-off or writeback is introduced.

BL-31 attribution follow-up adds importer-asserted, patient-scoped immutable note authorship and
true-or-unknown own-note credit in the score-free due list. Ordinary PSW clinical retrieval stays
denied; legacy source serialization/reset hashes are preserved. Decision033/migration013 record
the feedback-only freshness and exact current-citation gates. Exact-head CI remains required.
