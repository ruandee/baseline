# BL-14 synthetic loader and authored storyline inputs

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

- The loader now implements seeded identities, scoped writes, publication, idempotency and
  offline mode. Complete BL-10 integration and the real database acceptance below.
- Evaluate the manifest with the merged engine and verdict code, including all
  stable controls. Inputs alone do not establish engine statuses or verdicts.
- Resolve Mrs. L's spec inconsistency before claiming acceptance: her one-day
  -30% rate/+50% pause change can cross CUSUM H=4 immediately under the status
  rules, which prioritize `change` over `provisional`. The required
  `watch/recheck_1h (provisional)` is therefore not guaranteed. Preserve the stated
  deltas and settle the engine policy explicitly instead of tuning away this gate.
- Run real PostgreSQL/S3 loader, RLS, historical-cutoff, offline-context and verdict
  end-to-end checks. The loader must pass these gates before BL-14 is complete.

## Load and inspect (BL-10/11 integration required)

After migrations, choose presentation explicitly:

```sh
uv run python -m scripts.load_baseline_demo --offline --presentation all-history
uv run python -m scripts.load_baseline_demo --offline --presentation scenario-snapshots
```

Use a fresh demo scope for each example; these commands describe alternatives. `all-history`
loads all 360 immutable authored feature rows and scores all 30 days. `scenario-snapshots`
loads prefixes ending at Mrs. K/Mr. T day 27, Mrs. L day 29 and controls day 30 (353 rows).
It deliberately presents different historical event-time cutoffs, not one current-time unit.
Switching a populated full-history scope to prefixes fails instead of deleting later checks.
Prefixes can be extended to full history. The fixture timestamps are unchanged; this command
is retrospective replay with currently published source knowledge, not a historical knowledge
snapshot or a current-date demo reset.

The loader provisions the seeded tenant-0 importer/nurse and `uid("0/patient-i")` for i=0..11.
It may rename only an empty, recognized six-patient seed; foreign data or conflicting immutable
checks fail closed. Hosted bootstrap must consume all twelve patients from the output roster,
rather than retaining its older hard-coded six-patient list. The loader does not edit hosting,
frontend routes or reset behavior. Revoked assignments remain revoked.

All sources go through SourceInput ingestion and the worker; BL-10 backfill is completed
outside loader transactions before scoring. Exact canonical source/fact/tag spans are checked,
including the documented temperature observation 37.1 C (which is not a fever tag). Every check
is marked synthetic with quality provenance `authored_synthetic_features`, `audio_validated:false`,
no transcript and no word timestamps. No recording or quality-pipeline validation is invented.
Assessments use the actual engine/verdict service through pm_runtime and its tenant/patient locks.
A loader signature and source revision make unchanged reruns reuse checks and assessments.
Changed immutable inputs or withdrawn sources require a deliberate separate/reset demo scope.

Results are written to ignored `artifacts/baseline-demo/report.json`; the roster and short-lived
nurse token are written only to ignored `artifacts/baseline-demo/session.json`, never stdout or Git.
Keep that token server-side as PM_DEMO_TOKEN when wiring the existing synthetic demo server.
The report includes exact evidence quotes, per-resident expected/actual snapshot and latest
results, policy version, loaded row count and the explicit retrospective presentation. The
command exits nonzero when expected verdict/action acceptance differs. It does not coerce
Mrs. L, stable controls or Mr. T into the promised labels, or claim the original inconsistency
is resolved. The policy proposal #60 and separate 35% Mr. T scenario proposal need review.

`--offline` forces the shared keyword/template paths with no provider requests. Configured
provider mode is optional and uses the existing server provider settings. Ordinary CI uses stub.
Do not equate loader feature rows with the real-audio/runner acceptance gates.
