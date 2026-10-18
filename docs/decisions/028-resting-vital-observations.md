# 028: Explicit resting HR/RR observations as a vitals modality

Status: implemented for engineering review (BL-35). Thresholds are engineering assumptions,
not clinically calibrated limits. No diagnosis, autonomous treatment or clinical validation.

## Declared policy

Only explicit resting_hr_bpm and resting_rr_bpm concepts from present, patient-attributed,
system-authored observation facts are accepted. Generic heart/respiratory rate does not imply
rest. HR accepts bpm, beats/min or /min; RR accepts breaths/min or /min. Units are not guessed or
converted. Values must be finite and positive. Unknown effective time, conflicting values at
the same event time, unsupported units and invalid measurements stay unavailable, never zero.
Different event times never borrow values from one another. Missing HR can coexist with known RR.

The HR feature is two-sided with an absolute scale floor of 3 beats/min, as specified in 06.
The RR feature is positive-direction with a floor of 1 breath/min. Vitals alone uses
min_features=1 and cusum_min_features=1 so an isolated RR rise can contribute to the ticket's
explicit corroboration example; repeated evidence still uses the existing confirmation engine.
The user-approved engineering scope explicitly permits this modality-local declaration. Speech
features, thresholds and policy are unchanged. Direction, floors, feature counts, unavailable
features, adapter version and engineering_unvalidated status are echoed in modality parameters.
The registry's baseline/guard/window rules remain unchanged; these are not clinical ranges.

## Immutable provenance and new knowledge snapshots

Observations are grouped by exact effective time. Their deterministic check identity is derived
from patient, timestamp and resting-observation-v1, with exact fact citations. Modality
parameters retain selected baseline check identities and exact baseline fact IDs; no new raw capture,
patient table or secondary measurement copy is introduced. The current source lifecycle,
patient/tenant scope, polarity/experiencer and recorded versus effective times remain visible.
Late-recorded observations retain actual event time and are evaluated with currently published
knowledge, never as an assertion they were known earlier.

The worker refreshes after a resting-observation publication commits. It takes budget then
patient admission locks, rechecks access and current sources, and creates an idempotent current
revision snapshot. The same source/revision/settings signature reuses its assessment. A source
correction is new knowledge; it never mutates or revives an old assessment. The shared registry
reprojects other eligible modalities from their immutable captures at actual event times under
current settings. No old verdict/context/SBAR is copied and ADR015 global invalidation remains.
Fresh voice checks also project eligible resting observations, including privately scored PSW
checks. No generic public vitals-upload endpoint or model call is added. Source publication and
derived refresh are distinct: unavailable/error refreshes are audited without source text, and
cannot relabel a successfully published source or return a false normal measurement.

Non-speech evidence does not inherit speech-only SBAR statements. Such drafts remain explicitly
unavailable until a supported-sentence contract exists. Nurses can read the modality, actual
measurement time/value, unavailable features and exact source quote; source opening refreshes
assessment authorization/identity first. The normal resident/PSW flow never displays these scores.

## Narrow scoring scope

Migration012 follows motion011 and adds SELECT policy on facts only while the existing trusted
pm_check_scoring context matches the exact tenant/patient and an active checker assignment.
Ordinary PSW fact/evidence/overview reads remain empty or 404. The context is cleared before the
existing score-free CheckReceipt is returned. Tests exercise a real second assigned patient,
revocation and private corroboration without exposing scores in the PSW response. No generic
write or cross-patient source policy is broadened. Forced RLS and immutable source storage stay.

## Synthetic example and acceptance

An isolated Mrs. K-labelled test patient has six earlier RR observations at 16 breaths/min,
then two at 26 breaths/min an hour apart, alongside a provisional authored synthetic speech
change. The resulting vitals change corroborates speech using actual scoped persisted source
facts. The canonical twelve-resident cohort and accepted scenario/policy files are untouched.
This deliberately authored example is engineering evidence, not RR calibration or a diagnosis.

Unit/DOM and DB-backed tests cover RR/HR behavior, absent/invalid/conflicting values, exact source
quotes, temporal windows, idempotency, source amendment/retraction/purge, authorization, PSW
scoring isolation and readback after invalidation. Full exact-head CI is required before merge;
no physical sensor, real patient record, provider, golden audio or phone acceptance is claimed.
