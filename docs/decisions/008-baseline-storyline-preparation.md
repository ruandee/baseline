# 008: Prepare BL-14 inputs before the verdict/loader gate

Status: accepted for partial preparation, 2026-10-17.

BL-14 depends on BL-11 for demonstrated verdicts, but docs/06 explicitly allows
storyline JSON preparation in parallel. Commit a reproducible, synthetic-only
input manifest and generation script without a database loader, runtime contract
change or claim that BL-14 is complete. All expected verdicts remain unverified
engineering expectations until the merged engine and verdict table assess them.

Use explicit scenario snapshot times. The required changes occur on days 26–27
(Mrs. K/Mr. T) and day 29 (Mrs. L) of a 30-day series; later rows return to normal
input distributions. A future loader must preserve historical assessments or
agree on the demo's current-time presentation before asserting watch-list labels.

Retain Mrs. L's required deltas even though they can trigger CUSUM and prevent the
spec's required provisional status. This is an engine-policy gate, not a reason
to weaken acceptance or subtly change the fixture. Resolve it with BL-08/BL-11
before the BL-14 loader acceptance test is considered passing.

The fixture format is a preparation format, not an API contract. Source payloads
obey the existing `SourceInput` contract; synthetic feature rows have no audio
provenance and cannot serve as evidence that ASR or quality checks work. No real
runner data is included. Default validation uses no model/provider calls.

## Loader implementation (acceptance gates remain open)

The BL-14 branch now supplies `scripts/load_baseline_demo.py`. It provisions only known synthetic
identities, ingests immutable SourceInput documents and completes worker/context publication
before any runtime-role scoring. The report checks exact evidence spans and compares actual
verdicts/actions with the original manifest oracle. It never manufactures an audio transcript,
quality measurement or precomputed verdict, and returns nonzero on an acceptance mismatch.
Unchanged checks and source-revision/signature-matching assessments are reused on rerun.

Presentation must be explicit: all-history loads/scores 360 rows, while scenario-snapshots loads
353 prefixes with per-resident historical cutoffs. Neither silently changes timestamps to now.
An already fuller history cannot be destructively truncated by selecting a prefix. This is an
implementation presentation choice, not approval of the engine or Mr. T scenario amendments.
The fixed demo requires a separate current-time/snapshot/reset decision and actual host wiring.

Admin access is restricted to identity/assignment bootstrap. Sources and assessments use scoped
pm_runtime access and the service's tenant-then-patient admission lock order. Note extraction is
owned by BL-10; its backfill runs outside loader transactions before scoring, because publication
invalidates stored source-derived assessment text. The ignored report/session artifacts are the
only output location for the nurse token; no token is printed or committed.

Real PostgreSQL/S3 loader, evidence, idempotency, full-history/prefix and RLS tests are required.
The original policy/fixture mismatch remains a reported failing acceptance condition until a
separate reviewed proposal changes it; implementing a loader does not close BL-14.

Review hardening compares every existing source's system/document/version and canonical payload
hash with the complete manifest; the synthetic source-system stamp alone never authorizes an
extra context record. Bootstrap checks ownership before granting demo assignments. Expected
context support must occur inside the tag's own exact quote, and its linked exact fact span
must cover the tag; unrelated phrases elsewhere in a note are insufficient.
