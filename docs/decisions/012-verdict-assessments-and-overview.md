# 012: Verdicts are computed when a check is stored; the pages read them back

Status: accepted (17 Oct 2026, BL-11 and BL-13, issues #13 and #15).

## In plain words

`POST /checks` now scores every usable clip with the change engine, looks up the context tags that
are valid at the clip's time, applies the verdict table, stores an `assessments` row and returns
`change` and `assessment` in the same response. Unusable clips are stored for audit and never
scored. `GET /v1/watchlist` and `GET /v1/patients/{id}/overview` only read stored rows, so the
pages never recompute a verdict.

## Choices worth knowing

- **Engine mode.** `enrolled` once the patient has 3 or more usable `is_baseline` checks (the runner),
  otherwise `rolling` (the synthetic cohort).
- **Tags.** A tag counts if its source is not retracted or purged (decision 007) and the check time
  is inside `valid_from..valid_to`. Reasons keep only amplifiers for `escalate` and `watch`, and all
  valid tags for `explained`.
- **Escalation budget.** 3 per 8-hour shift (07:00, 15:00, 23:00 `PM_SHIFT_TIMEZONE`, default
  America/Toronto). An escalation beyond the budget is stored as `escalate` with `over_budget`.
  Counting is per tenant, through RLS.
- **No-escalate profile.** Patients in `PM_NO_ESCALATE_PATIENTS` (comma-separated UUIDs) get
  `watch` instead of `escalate`, with `no_escalate` and `would_escalate` flags so the page can say
  "would escalate, disabled for this profile".
- **Where flags live.** There is no column for them, so they sit in `assessments.params`, next to
  the thresholds that produced the verdict. No migration was added, so the KAZE migration number is
  unaffected.
- **Display name.** Patients have no name column. `display_name` is `patients.external_id`, so the
  cohort loader (BL-14) must set `external_id` to the name shown ("Mrs. K").
- **SBAR.** Only the template path exists (the spec's fallback), stored with `source: "template"`.
  Sentences cite `check:<check id>` or a context tag's fact id. Wording says "their usual" rather
  than "her usual" because no pronouns are stored. Gemini drafting (BL-12) is not built.
- **Per-feature `scale`.** `change.per_feature` and `baseline.features` expose the engine's floored
  `scale`, not raw MAD, so the band on the resident page is median plus or minus 2 scale.
- **Quote highlight.** `reasons[].match` spans the whole stored quote. Free-text notes will narrow
  it when Gemini extraction (BL-10) lands.

## Not done

Temperature "documented and normal" is not returned yet (no reader for observations that did not
create a tag). Gemini note extraction and SBAR drafting. Daily medians use `time_bucket`, which
needs the Timescale extension (already in the image).
