# 025: Declared signal registry and scoped multimodal corroboration

Status: implemented for engineering review (BL-30); exact integrated CI required.

The registry declares feature name, modality, concerning direction and absolute scale floor.
Speech retains the accepted multifeature-cusum-v2 features, thresholds, baseline selection,
confirmation and signed pitch streams unchanged. Existing speech engine tests remain unchanged.
Only speech is registered in runtime; the second modality in tests is a synthetic probe. This
change does not implement gaze, wearables, device capture or autonomous diagnosis/treatment.

Each modality is evaluated against its own earlier usable checks with the same prompt. Device
preference, enrolled versus rolling selection and exact thresholds remain visible in parameters.
Feature-name collisions and invalid direction/floor/count declarations fail at registration.
Future adapters may declare feature counts explicitly; no shipped speech threshold is relaxed.

## Corroboration and persisted admission

At a triggering signal's event time, the latest known assessment per other modality is eligible
only within the preceding 24 hours, inclusive. Future readings cannot influence an earlier signal;
a newer quiet result replaces an older flagged result. The strongest eligible status is returned.
Two or more provisional/change modalities set corroborated=true. A corroborated provisional
retains its observed provisional status but passes verdict_status=change to the existing verdict
table. Enrolling stays unknown, never a negative finding. Missing registered modalities report
status=unavailable with no time, scores or evidence; stale modalities report current=false.
This is an engineering corroboration rule, not a clinically calibrated probability.

The internal assess_modality hook authorizes and locks before calling an adapter's scoped history
loader. Adapters own immutable capture storage and feature extraction; there is no generic public
signal upload endpoint or client-controlled registry. Non-speech adapters require care-team scope
and nonempty UUID fact citations belonging to that patient. Missing/foreign, future, expired,
retracted, purged, unpublished or superseded source evidence fails closed. The hook records
signal event time, check identity, exact scores, citation/source identities and current source
revision atomically. Existing patient-wide source lifecycle invalidation withholds old snapshots.
Authorization is rechecked under the admission lock. PSW-only callers cannot use this non-speech
hook or read its results; existing voice-only scoring and score-free receipts remain unchanged.

KAZE session signals stay session-local and never corroborate resident signals. Resident budget
and profile rules apply to modality assessments; KAZE continues its independent policy. Migration
010 adds the assessment corroborated column and updates the existing narrow tenant-budget
aggregate to count non-speech signal event time while excluding session signals. Existing forced
RLS and composite patient ownership on assessments remain unchanged; no patient table is added.

## Read compatibility and drafts

New assessment features are stored per modality. Legacy flat speech rows remain readable without
rewriting history. Overview/watchlist expose corroborated and modalities, with status, event time,
check/evidence IDs, current eligibility, scores and parameters. Existing change.per_feature stays
a flat speech projection. Speech charts and baseline bands always use the latest speech
assessment, even when a different modality supplied the latest overall verdict. Non-speech
features remain explicit in modalities rather than being drawn as speech values.

Any current flagged non-speech contribution withholds the speech-only SBAR and returns
unavailable_multimodal_evidence. It cannot inherit speech-specific sentences/citations or trigger
provider enrichment as though it were a voice-only draft. A future adapter needs its own exact
supported-sentence contract before multimodal SBAR/export is enabled. Single-speech template and
configured drafting retain the original flat feature inputs through the compatibility helper.

## Verification

Original speech engine and registry tests cover unchanged thresholds, separate histories,
24-hour eligibility, unavailable states and two-modality corroboration. DB-backed tests exercise
actual runtime-role publication/readback, flat/nested compatibility, latest quiet versus older
flag, future/stale exclusion, source lifecycle, ownership, PSW denial, revocation and budget
aggregation. Default tests use only synthetic data/stubs; no model, sensor or paid-network calls.
Full integrated CI, including PostgreSQL/S3 and stub evaluation, is required before merging.
