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

## PROPOSED Mr. T scenario amendment (separate review branch)

Paired with policy PR #60 only, change the authored day-26/day-27 pause ratio AND mean-pause
increases from 20% to 35%. Preserve speech-rate -15%, all source documents, all timestamps and
all other residents. This is an explicit change to the original docs/06 Mr. T acceptance input,
not a threshold adjustment, clinical estimate, or a way to hide a failing existing gate.
Generator, regenerated fixture and exact-delta invariant test change together on this isolated
proposal branch. The main BL-14 loader branch continues to report the original mismatches.

The required expected explained result is contingent on reviewed engine policy #60 and actual
context/verdict loader evaluation. No approval or clinical validation is implied by this proposal.
The team must accept both changes and the independent snapshot/presentation choice before
claiming the scripted scenario works as a current demo. Do not auto-close BL-14 on this PR.
