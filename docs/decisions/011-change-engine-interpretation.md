# Change engine: how the spec's open points were read

`baseline/engine.py` (BL-08) implements "Change engine" in `docs/06-baseline.md`. The spec leaves a few points open; these are the readings the code and its tests rely on. Later tickets (BL-09 onward, BL-32) should not change them without amending this record.

- **One baseline per evaluation.** The baseline (median and MAD) is computed once for the new check. Every check in the sequence (the last 20 usable checks with the same `prompt_version`, ending with the new one) is scored against that baseline to build EWMA and CUSUM. Nothing is stored.
- **Starting values.** EWMA and CUSUM both start at 0, so the first check in a sequence is smoothed toward 0, which is what a baseline-typical check scores.
- **Device preference applies to the sequence as well as the baseline.** Same `device_id` when at least 3 checks match, otherwise all devices. Otherwise another device's systematic offset would drive CUSUM on a device whose own baseline is fine.
- **Missing features.** A feature that is `None` on a check is skipped for that check (no EWMA or CUSUM update) and left out of the fused mean. A feature with fewer than 3 baseline values is not scored.
- **"Previous usable check within 24 h"** is the immediately preceding check in the sequence, and only counts if it is at most 24 h before the new one.
- **CUSUM alarms on the new check's cumulative value only.** With k 0.5 and h 4, one clip with dz of 4.5 or more on a single feature trips the alarm by itself and reports `change` rather than `provisional`. Sustained smaller drift can also alarm without two consecutive checks over the z threshold. This follows the spec's "or any CUSUM alarms"; if a lone strong clip should stay `provisional`, raise `PM_CUSUM_H` rather than special-casing the engine.
- **Unusable checks are refused.** `evaluate` raises `ValueError` for a new check with `usable = false`; unusable history is dropped. If no feature has 3 baseline values the status is `enrolling`, never `none`, so a missing baseline is not read as a negative finding.
- **Mode is chosen by the caller** (enrolled for patients with `is_baseline` checks, rolling otherwise); the engine does not infer it.
- **Out of scope here:** the `PM_Z_THRESHOLD_FREE` (2.5) rule for `free-conversation-v1` belongs to BL-32. Until then every prompt version uses `PM_Z_THRESHOLD`.

## Review hardening

Engine settings now fail startup on nonfinite or out-of-range values: z thresholds and
CUSUM alarm height must be positive, CUSUM allowance nonnegative, EWMA lambda in
`(0, 1]`, and required feature count between 1 and the four available speech features.
This prevents invalid environment overrides from producing automatic alarms or disabling
confirmation. Defaults and the documented single-clip CUSUM behavior are unchanged.
