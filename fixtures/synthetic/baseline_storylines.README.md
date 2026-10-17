# BL-14 loader and authored synthetic storylines

The manifest contains12 fictional residents and360 authored feature rows across30 fixed UTC days,
not extracted recordings. Seed20261017 draws resident reference values from docs06, with daily
Gaussian noise clipped at1.5 generating SDs; realized sample SD is consequently lower. Scripted
changes multiply reference values exactly. `usable:true` is authored input, not an audio-quality
claim. No runner/live profile, audio, transcript or credential is committed.

The user explicitly approved policy#60 and Mr. T scenario#61, now adopted together here.
Accepted `multifeature-cusum-v2` uses corroborating features and signed pitch streams. The authored
Mr. T scenario changes BOTH pause ratio and mean pause from+20% to+35% on days26/27, retaining
speech-rate-15%. This is a reviewed demo scenario, not an empirical claim about dentures.
K/L/control inputs, notes, timestamps and seed are unchanged. Strict scenario-snapshot acceptance
requires actual K escalate/4at_now, T explained/none, L watch/recheck_1h and nine within_normal
controls; the loader never coerces results or hides mismatches.

## Run

Migrate first, then choose a presentation explicitly:

```sh
uv run alembic upgrade head
uv run python -m scripts.load_baseline_demo --offline --presentation all-history
uv run python -m scripts.load_baseline_demo --offline --presentation scenario-snapshots
```

The two loader commands are alternatives; use a fresh scope when changing from a fuller history
to prefixes. All-history loads360 immutable checks and scores all30 days. Scenario-snapshots
loads353 prefixes: K/Tthroughday27(2026-10-14T14:00:00Z), Lthroughday29(2026-10-16T14:00:00Z),
controls throughday30(2026-10-17T14:00:00Z). The scenarios have different historical cutoffs.
Checks after the scenario recover, so full-history latest results are normally within_normal;
declared-snapshot acceptance is separately reported. Fuller histories cannot be truncated by
this loader; prefixes can be extended. It never rewrites timestamps to now. This is event-time
replay using currently published evidence, not an earlier knowledge snapshot or current-date reset.

## Publication, scope and idempotency

The loader provisions seeded tenant0 importer/nurse and uid("0/patient-i") for i0..11. Only empty
recognized six-patient seeds may be renamed. Every existing source must match the manifest's full
system/document/version/payload hash; existing checks must match authored values and non-audio
provenance. Foreign/unlisted data and revoked access fail closed. Admin access only provisions
identities/assignments; ingestion, retrieval and scoring use pm_runtime scope and RLS.

All SourceInput records publish through immutable ingestion/worker before ANY assessment. Shared
BL-10 backfill owns its transactions and finishes before scoring. Expected context must occur in
the actual exact tag quote, covered by an exact linked canonical fact span. Medication orders
remain order events;37.1C is a documented observation, not a fever tag or a diagnosis. Absence of
other sources is unknown context, not a documented negative finding. Withdrawn sources cannot be
revived by rerunning. Signature/source-revision matching reuses unchanged checks/assessments.
Changed immutable inputs require a deliberate fresh/reset scope; old checks are never rewritten.

Feature rows are synthetic, with quality provenance authored_synthetic_features and
audio_validated:false; no transcripts or word timestamps are fabricated. Assessment service
locks tenant then patient. Configured loader scoring deliberately keeps the service template;
it does not make hundreds of post-commit SBAR model calls. --offline forces keyword/template
paths with no network/model requests. Real-audio and runner acceptance remain separate.

## Output and remaining readback gates

Ignored artifacts/baseline-demo/report.json records exact source quotes, expected/actual declared
snapshot and latest results, policy, row counts and retrospective semantics. Any mismatch exits
nonzero; no verdict is coerced. The nurse token and12-patient roster go ONLY to ignored
artifacts/baseline-demo/session.json, never stdout or Git. Hosted bootstrap must consume that
roster instead of its older hard-coded six-patient list; use its token server-side as PM_DEMO_TOKEN.

Passing historical fixture acceptance does not establish a current-time demo. Hosting/frontend/reset
owners still need to agree on current-time/snapshot presentation and readback wiring; displaying
Mrs. K's documented normal temperature in overview/UI remains a separate requirement. Public HTTPS,
phone/latency checks, real recordings and runner clips are not validated by this loader. See
decision008, accepted policy decision019 and the build tracker for actual remaining gates.
