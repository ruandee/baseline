# 016: Mock Vox encounter adapter analyzes resident speech only, as its own prompt

Status: proposed (17 Oct 2026, BL-32, issue #34). Implements the "Vox Advantage adapter (mock)"
section of `docs/06-baseline.md` and records where the build differs from it.

## In plain words

`POST /v1/integrations/vox/encounters` takes a recorded care conversation with diarized segments
and turns the resident's part of it into an ordinary voice check. It is a **mock**: we found no
public Vox Advantage API, so the contract is ours. The response carries `mock: true` and
`adapter: "vox-advantage-mock-v1"`, and the OpenAPI summary says it is not a real
PointClickCare/Vox integration. Nothing here talks to PointClickCare or Vox.

## Contract

Multipart fields: `resident_id` (patient UUID), `audio`, `segments` (JSON
`[{speaker: "resident"|"staff"|"other", start, end, text?}]`, 1 to 400 items), `consent`,
`encounter_ts` (timezone-aware, at most 5 minutes in the future; stored as `device_ts`).

Order of checks, each one stopping the request:

1. Bearer identity, then the care-team gate on `resident_id` (`nurse`/`importer` assigned to that
   patient in the caller's tenant). Anyone else, any other tenant's or unassigned patient: 404,
   with no audit row, no consent evaluation and no audio work.
2. Per-request consent: exactly one `consent` part whose raw value is `true` (no trimming, no
   case folding). Missing, empty, `false`, `True`, ` true`, a repeated `consent` part (even
   `true` twice) or anything else returns 422 `consent_not_given` and commits one audit row
   (`action=vox_encounter`, `result=consent_refused`). No check, assessment or audio is stored, and
   the audio is never decoded. This is checked before the other fields are validated, so a
   refusal is audited even when the rest of the request is malformed.
3. Field validation: bad segments, timestamp or missing audio is 422 `invalid_request` without
   echoing the submitted text. Undecodable audio is 422 `invalid_audio`; missing ffmpeg is 503.
4. Analysis and storage through the same `store_check` as `POST /checks`, which re-runs the care
   gate after processing, takes the shared `lock_assessment` order (tenant budget, then patient)
   and runs the shared assessment pipeline. Success writes `create_check` and `vox_encounter/ok`
   audit rows. After that transaction commits, the same `enrich_assessment_sbar` step as
   `POST /checks` runs (decision 014; a no-op with the stub provider).

The response is `VoxEncounterResult`: `usable`, `reasons`, `resident_speech_s`, `analyzed_s`,
`truncated`, per-speaker segment counts and the full `check` (same shape as `POST /checks`).

## Choices and trade-offs

1. **Resident-only extraction removes crosstalk.** Resident segments are merged, clipped to the
   decoded audio and have every overlap with a staff or other segment cut out; slivers under
   50 ms are dropped. Staff speech is never analyzed or stored, even when diarization overlaps.
2. **Cut in NumPy, not an ffmpeg `atrim`/`concat` graph.** The spec suggested ffmpeg filters. The
   upload is decoded once with the existing normalize step (16 kHz mono, 80 Hz high-pass) and the
   resident samples are sliced and concatenated in memory. The result is the same, and no filter
   graph is built from client-supplied numbers.
3. **Segment `text` is ignored.** It is validated for size and shape only. The stored transcript
   comes from our ASR run on the resident-only clip, so staff words cannot reach storage.
4. **Limits.** The whole body stays under the 2 MB `PayloadLimit` cap. Encounters longer than
   120 s are refused (`invalid_audio`); ffmpeg stops decoding just past the limit, so a long file
   is never decoded in full (`POST /checks` now uses the same bounded decode at 30 s). At most
   60 s of resident speech is analyzed (`truncated: true` beyond that) to bound Whisper time.
5. **At least 8 s of VAD-voiced resident speech** (after overlap removal and the analysis cap,
   excluding silence inside diarized turns), else `usable: false`,
   `reasons: ["too_little_resident_speech"]`. Like other unusable clips the row is stored for
   audit and never scored, and Whisper does not run.
6. **Prompt separation.** Checks are stored with `mode = "resident"`,
   `prompt_version = "free-conversation-v1"`, `device_id = "vox-mock"` and `is_baseline = false`.
   Engine history was already prompt-scoped (decision 015); the assessment now records
   `prompt_version` in `params`. Free conversation skips the on-script quality reason only; every
   other gate still applies.
7. **Free-conversation threshold.** `PM_Z_THRESHOLD_FREE` (default 2.5, must be positive) replaces
   `z_threshold` for that prompt only. `provisional_z`, CUSUM and the other engine parameters are
   unchanged. The stored `params.z_threshold` shows the value actually used.
8. **Read models stay on one prompt.** The resident overview charts the checks of the prompt its
   latest assessment used (`baseline.prompt_version` is new), so a Vox point is never drawn on a
   counting-prompt band. The watch-list sparkline shows the counting prompt only. **ON HOLD:**
   Dee has not yet decided on this read-model behavior. It ships as built, but it is not accepted
   and may change.
9. **Encounter audio is always deleted.** The work directory (raw upload and decoded wav) is
   removed after analysis whatever `PM_KEEP_AUDIO` says, because a raw encounter contains staff
   speech. `PM_KEEP_AUDIO` still applies to `POST /checks` only.

## Interaction with BL-31 / decision 017

There are two consent gates with distinct errors. Standing resident consent is now integrated
from decision017 (migration007 after006): after the care-team gate, the route requires stored
granted consent for `vox_encounter` before decoding, then rechecks inside locked `store_check`.
Unknown, declined, withdrawn or expired standing consent returns403 `consent_required` and
commits a separate `check_blocked_consent` audit row. A withdrawal during analysis rolls back
publication. Existing `voice_check` consent never substitutes for encounter consent. PSWs remain
forbidden from the Vox route even though the shared check writer supports their ordinary checks.
The separate per-request consent part records permission for this encounter; only one literal
`true` passes, otherwise audited422 `consent_not_given`. Contract tests exercise the two error
classes, expiry, scope isolation, withdrawal during analysis and unchanged allowed capture.

## Not done

- No UI. The spec's "labelled as such in the UI" applies to whichever page later shows Vox
  results; the API marks every response as a mock.
- The fixture is `fixtures/synthetic/vox_encounter_mrs_k.json` (timeline and invented text only).
  Its teammate-voiced audio stays out of Git (`data/raw/`), and real recordings remain on hold. Tests
  synthesize tones on the fixture timeline (resident 140 Hz, staff 230 Hz), so this proves
  resident-only extraction, not real-speech accuracy.
- The adapter does not create SBAR notes or the out-direction DocumentReference (BL-33).
- Whether Vox checks should show on the watch list sparkline, or their own chart, is a UI decision.
