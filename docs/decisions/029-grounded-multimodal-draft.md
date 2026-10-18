# 029: Deterministic grounded multimodal draft and preliminary export

The nurse experience in section 06 requires an editable draft for watch/escalate assessments.
ADR025 withheld non-speech drafts because the voice-only template and export could not support
their evidence. This follow-up replaces that withholding only when exact registered capture and
baseline provenance are available. It does not change signal thresholds, verdicts or actions.

The server constructs S sentences from each contributing current modality's declared feature
labels/units, actual event time, measured values and computed baseline medians. Each comparison
cites both the current immutable capture/facts and all captures/facts selected for that baseline.
Missing measurements, unknown labels/units, unavailable baselines or citation limits withhold
the whole draft. No voice result is invented for a non-speech primary capture.

B uses current attributed context or states that context was not supplied. A reports engineering
status separately for each modality and the already computed corroboration flag; thresholds are
explicitly not clinically validated. R copies the existing standard action label. This path never
calls a provider. Existing speech-only template/provider behavior remains available separately.

Preliminary DocumentReference export resolves every cited voice capture under tenant/patient
RLS, usable non-session scope and one prompt version. Fact citations require currently published,
unretracted, unpurged, unsuperseded sources and unexpired facts. Assessment revision and care
assignment are rechecked under the patient lock. Contributing capture age is limited to the
existing 24-hour corroboration window on read/export; no threshold is changed. Source revision
invalidates snapshots as before. Nonvoice primary IDs use a signal-capture identifier, never a
voice-check identifier. Multiple voice references include actual baseline measurements.

The nurse overview withholds an unavailable draft and supplies only its authorized cited voice
captures for readback. Citation buttons reload the same current assessment before showing those
measurements or source quotes. Export stays preliminary and unsigned; local human edits remain
separately labelled unverified previews, with no writeback or sign-off implementation.

Verification includes RR-only, speech plus vitals, current/baseline citations, source lifecycle,
capture expiry, revoked access, unknown/provenance gaps, exact standard actions and real DOM
readback. Motion uses the same contract when its immutable history exposes exact fact provenance.
