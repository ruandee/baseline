# 030: Live volunteer demo, 30-second capture and exploratory stairs

Status: accepted by Dee in the implementation conversation, 2026-10-18.
Affected work: BL-06, BL-15 and BL-17. This is a demo protocol revision, not clinical validation.

## Decision and rationale

Dee replaces the proposed remote teammate/marathon call as the live speaker. The demo receives
an actual browser recording through `/check`, compares it with that same consenting volunteer's
rested baseline, and shows the actual result. An ordinary telephone call is not ingested.
A normal result is a successful live check-in. A scripted synthetic resident separately shows
the change/context/verdict pathway. Do not attach fictitious marathon context to Dee's recording.
Breathlessness detection is deferred; no new feature or clinical thresholds are adopted.

Core `/check` capture (resident, runner and live) now auto-stops at 30 seconds instead of 15;
manual Stop remains available. The existing server maximum stays 30 seconds, the whole multipart
body limit stays 2 MB, and quality/consent/authorization gates are unchanged. Browser scheduling
and encoding can overshoot a nominal timer: device acceptance must verify real uploads and use
manual Stop once the prompt is complete. This does not relax server limits. The separate KAZE
session recorder retains its own 15-second/session-expiry limit.

Five distinct rested takes are enrolled through `POST /v1/patients/{id}/checks` with runner mode
and `is_baseline=true`. The on-stage check uses `mode=live`, `is_baseline=false`, the SAME patient
and device ID. Runner mode's UI shows only a receipt; live mode shows the decomposition. The
Saturday-only browser baseline checkbox is not used or changed. Consent is the volunteer's
actual recorded decision, never synthetic fixture consent. Enrollment cannot reuse a single
recording five times or convert slow/pausey/stairs takes into baseline material.

## BL-06 acceptance revision

The original four-assertion run on Dee's local recordings produced 3 passes and 1 failure:
all four clips usable; slow speech 113.13 to 82.74 words/minute; deliberate-pause ratio 0 to
0.3423 with 11 detected pauses; stairs pitch 184.27 to 184.18 Hz, failing the original >193.48 Hz
expectation. This original failure remains part of the record.

The required gates are now all four recordings usable, deliberately slow speech decreasing
speech rate, and deliberate pauses increasing pause ratio/count. Stairs remains a required
usable recording with reported exploratory features, but has no required pitch or timing
direction. No threshold was tuned to make it pass. The slow suite has three acceptance tests;
its fixture prints the normal/stairs comparison with `-rA`. Absence of an acoustic change does
not establish absence of breathlessness. One person's recordings do not validate exertion
detection, false-alarm rates, the change engine or clinical usefulness.

Original recordings, transcripts and private receipts remain outside Git/CI. Synthetic default
tests remain offline. Real-device, hosted API enrollment and rehearsals remain separate gates.
