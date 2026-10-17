# BL-14 storyline inputs (partial preparation)

`baseline_storylines.json` contains 12 fictional residents and 360 authored feature
rows, with fixed UTC event times, one row per resident per day. These values are
synthetic measurements, not extracted recordings. No runner, live profile, audio,
transcript, quality measurements, database IDs or credentials are included.
`usable: true` is fixture input, not a claim that audio passed the quality pipeline.

Regenerate from the repository root with
`python -m scripts.prepare_baseline_storylines`. The seed is 20261017; resident
reference features use the ranges in docs/06, with daily Gaussian noise using its
stated SDs, clipped at 1.5 SD to avoid accidental control outliers. Consequently the
realized sample SD is lower than the requested generating SD. Scripted changes are
exact multipliers of `reference_features`, with normal pitch and other unspecified
features left at their daily values. For Mr. T, “pauses +20%” applies to both pause
ratio and mean pause duration.

The manifest has `schema_version: 1` and `status: storyline_inputs_only`. Each
resident has `id` (a synthetic external reference), `display_name`,
`reference_features`, `checks`, `sources`, `expected_context`, and
`expected_assessment`. Checks supply explicit `ts`, prompt, device, mode, flags and
four features. `sources` are directly valid `SourceInput` payloads for the existing
ingestion path. `expected_context` is an engineering oracle, not precomputed tags:
quoted note spans must be found in published canonical text, while structured
record spans must be resolved by the existing structured extractor. The temperature
of 37.1 C is an observation, not a fever tag. The medication is an order event,
not evidence of administration or a diagnosis. Missing sources on other residents
mean no supplied context, not documented clinical negatives.

`expected_assessment` records the spec's desired verdict/action at an explicit
scenario snapshot; every result remains `pending_bl11_loader`. Mrs. K and Mr. T
are assessed on day 27, Mrs. L on day 29, controls on day 30. The changed residents
return to generated normal feature values on later days. A loader must explicitly
choose historical scenario snapshots or agree on a changed demo timeline; it
cannot use day 30 as a shared latest-check snapshot and promise all three labels.

## Remaining BL-14 gates

- Implement `scripts/load_baseline_demo.py`, seeded tenant/nurse assignments,
  scoped synthetic writes, immutable source ingestion/publication, idempotency and
  `--offline` context extraction after BL-11 is available.
- Evaluate the manifest with the merged engine and verdict code, including all
  stable controls. Inputs alone do not establish engine statuses or verdicts.
- Resolve Mrs. L's spec inconsistency before claiming acceptance: her one-day
  -30% rate/+50% pause change can cross CUSUM H=4 immediately under the status
  rules, which prioritize `change` over `provisional`. The required
  `watch/recheck_1h (provisional)` is therefore not guaranteed. Preserve the stated
  deltas and settle the engine policy explicitly instead of tuning away this gate.
- Run real PostgreSQL/S3 loader, RLS, historical-cutoff, offline-context and verdict
  end-to-end checks. No loader or backend behavior is changed by this preparation.
