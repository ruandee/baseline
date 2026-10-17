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
