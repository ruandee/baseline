# 019: Proposal — corroborated, ongoing CUSUM alarms

Status: proposed for review, not an accepted replacement for decision 011, 2026-10-17.

## Problem and evidence

Decision 011 follows docs/06 literally: any single-feature CUSUM alarm immediately yields
`change`, before the provisional rule. That makes Mrs. L's isolated severe clip a change
rather than the promised provisional result. Against the unchanged draft BL-14 inputs,
the original engine also flags stable Resident 06 at day 30 through pitch CUSUM. Accumulating
`abs(z) - k` in one pitch stream pools opposite-direction noise into a positive trend.
Large historical CUSUM values can also maintain a flag after the current measurements recover.

This branch proposes a **behavior change**, not a bug fix consistent with the original spec.
It needs explicit review/acceptance and corresponding spec/acceptance changes before merge.
No threshold is adjusted and no clinical sensitivity/specificity is established.

## Proposed status policy

- Preserve the existing instantaneous confirmation: at least `PM_MIN_FEATURES` features
  above `PM_Z_THRESHOLD` on current and previous usable checks within 24 hours gives change.
- Pitch uses separate signed streams: `C+ = max(0, C+ + z - k)` and
  `C- = max(0, C- - z - k)`. The displayed CUSUM is `max(C+, C-)`.
- A supported feature has the relevant directional CUSUM at least H and current directional
  deviation strictly greater than k. Pitch must support the corresponding signed stream.
- CUSUM gives change only when at least two **same features** are supported on both the
  current and preceding usable check within 24 hours. Pitch direction must also match.
- Otherwise, at least two currently supported CUSUM features give provisional. Preserve the
  existing at-least-`PM_MIN_FEATURES` deviations above `PM_PROVISIONAL_Z` provisional rule.
- One-feature CUSUM alone never sets status. A high residual CUSUM without ongoing deviation
  remains a diagnostic; it does not keep an alert active after recovery.

All baseline, prompt, temporal, device preference, feature scale and 20-check sequence rules
remain unchanged. The current baseline is still used to reconstruct the entire scored sequence;
previous-score reconstruction is not the previous assessment's original historical snapshot.
Every result echoes `policy_version=multifeature-cusum-v2-proposal`, CUSUM minimum features,
confirmation hours, ongoing-deviation requirement and signed-pitch mode in `params`.

## Deliberate tradeoffs and required fixture amendment

The original ability to flag a single accumulated feature is removed. Two-feature mild drift
can still accumulate below the instantaneous threshold, first provisional then change on a
supported repeat within 24 hours. A daily check delayed beyond 24 hours will not confirm; changing
that window is a separate decision. Alternating-sign pitch still affects two-sided z/EWMA/fused
diagnostics but no longer pools both directions into one CUSUM. False alarms can still occur;
passing one authored fixture set is not false-alarm calibration or clinical validation.

**The original Mr. T fixture does not meet this proposal:** its 15% speech-rate drop and 20%
pause increases provide only one sufficiently strong feature. It returns none rather than
explained. To retain the intended two-feature denture story, a separately reviewed fixture/spec
amendment must change BOTH pause ratio and mean pause increases to 35% on days 26 and 27.
This is an explicit authored demonstration scenario change, not an empirical claim about
dentures, and not a secretly tuned threshold. This engine branch does not edit the fixtures.

## Reproduction and acceptance evidence

Evaluation of all 360 draft BL-14 feature rows with this implementation and original values:
36 enrolling, 321 none, 2 provisional, 1 change. All 270 checks from the nine controls have no
provisional/change flags. Mrs. K is provisional day 26 and change day 27, then none days 28–30;
Mrs. L is provisional day 29 and none day 30; original Mr. T remains none.

With ONLY the above 35% override applied to a copy in memory: 36 enrolling, 319 none,
3 provisional, 2 change. Mr. T becomes provisional day 26, change day 27, then none days 28–30.
Mrs. K, Mrs. L and controls retain their results. Context/verdict integration is separately
required to demonstrate escalate, explained and watch; this run establishes engine statuses only.

Tests preserve original invariants and add first/extreme alarms, gradual multifeature drift,
pitch sign alternation/reversal, one-feature diagnostic-only alarms, recovery, missing features,
unusable/wrong-prompt/future history and the exact 24-hour boundary. The original >24-hour
single-alarm change test now explicitly expects provisional under this proposed policy.

The inconsistent latest snapshot chronology is a separate BL-14 decision; historical day-27
Mrs. K/Mr. T labels do not automatically become current day-30 results. Approval requires engine,
fixture/spec and loader snapshot decisions to be reviewed together, followed by full CI.
