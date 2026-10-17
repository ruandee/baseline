# 015: Assessment evidence expires with source revisions

Status: proposed (17 Oct 2026, review fixes for BL-11/BL-13, issues #13 and #15).

## Problem

Assessments copy context quotes and generated/template prose. Filtering current context tags alone
cannot revoke those copies after a source correction, visibility change, retraction or purge.
The initial integration also truncated history before selecting baselines and allocated shift budget
slots without serializing concurrent uploads. CI skipped the browser upload contracts without ffmpeg.

## Decision

- An assessment records the current patient source revision and source IDs in `params`. Read endpoints
  return only assessments whose revision still matches, and whose `invalidated` flag is false. Existing
  rows without revision provenance are withheld rather than asserted current.
- Every source revision bump clears copied `reasons` and `sbar` on that patient's assessments and marks
  them invalidated, in the same transaction as source publication/mutation/purge. Numeric check scores,
  verdict audit fields and escalation-budget flags remain. This conservative invalidation includes
  unrelated source publications; it favors explicit missing current assessment over stale evidence.
  A new usable check produces the next assessment; read endpoints do not silently recompute one.
- Active context requires a published, non-retracted, non-purged source with no published active
  superseding source. Context provenance includes `source_id` and its explicit `valid_to`.
- History is scoped by patient and prompt before evaluation, with no arbitrary row cap. The pure engine
  retains its existing enrolled/rolling/window/device/sequence rules. This synthetic prototype has no
  retention-volume optimization; future bounded queries must preserve every baseline/sequence rule.
- Check admission acquires the tenant budget advisory lock before the patient advisory lock. This
  serializes budget allocation and same-patient confirmation history. Watchlist uses the same order;
  overview and existing source operations use the patient lock. Read endpoints recheck access after
  waiting. Budget counts retain RLS scope: they never disclose inaccessible patients' assessments.
- Install ffmpeg in CI and assert usable browser uploads return an enrolling change/assessment when
  no baseline exists. Real Whisper/golden-recording tests remain explicitly slow and excluded.

## Contracts and limitations

No migration, endpoint or response schema removal is required. `latest_assessment` and
`latest_verdict` can be null after source changes until a fresh usable check. `context_tags` adds
`source_id` and `valid_to`. Purge removes copied clinical prose from assessment storage as well as
facts/context tags; retained numeric metadata has no copied source text.

This does not implement BL-10/BL-12, the documented-normal-temperature reader, or real-audio acceptance.
Regression coverage includes retraction, purge, visibility changes, superseding corrections, retained
baseline after sixty newer checks, and concurrent allocation of the final escalation slot.
