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

## BL-20 — Container hosting preparation (acceptance pending)

Opt-in `compose.demo.yaml` adds the ffmpeg image, seeded tenant-0 worker, same-origin frontend/API
and Caddy HTTPS proxy. Hosted startup requires explicit hostnames, a deployment signing secret
and a valid seeded nurse token. Only Caddy publishes public ports. Explicit migration/bootstrap
commands precede startup; the six-patient seed is empty until BL-14/21 cohort/reset integration.
See [deployment recipe](demo-hosting.md) and [decision 007](decisions/007-demo-hosting.md).
No public host was provisioned. Container/service validation, phone LTE recording/result and
latency gates remain outstanding; issue #22 must stay open.

Local validation on Windows/Python 3.14.2: ruff passed; unit tests 47 passed, 7 skipped, 2 slow
tests deselected. Overlay YAML parsed and runtime port/admin-URL assertions passed. Docker is
unavailable here, so image build, Compose runtime validation, migrations, DB-backed tests and
stub evaluation were not run. Unit skips include missing ffmpeg; the container installs it.
