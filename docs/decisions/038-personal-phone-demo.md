# 038: Genuine personal-baseline phone demo

Date: 2026-10-18. Scope: BL-15 follow-up, using existing BL-17/18 APIs.
Status: local implementation; deployment, enrollment and physical-phone rehearsal pending.

The runner is unavailable. Dee requests actual recording, comparison against Dee's own rested
baseline, prompt nurse updates and repeated check-ins. This replaces the selected presentation
in decision036 with the genuine measurement direction of decision030. A normal result is valid;
no verdict or temporal override is introduced.

The entry is direct URL only: `/unit?demo=personal` is the nurse screen, with a scoped phone link
to `/check?mode=live&demo=personal&patient=<id>`. Neither website header links to a demo. Old
`demo=handoff`, `demo=days` and `demo=legacy-days` entries redirect to the new screen and discard
old room capabilities. The authored implementations remain explicitly archived as
`demo=archived-handoff` and `demo=archived-days`, preserving their disclosed behavior and tests.

Only the session's dedicated live capture identity, outside the scripted cohort, is admitted.
There is no implicit fallback to a fictional resident. Existing server authorization, counting
profile, current consent and evidence rules remain authoritative. Configure explicit English
and record the volunteer's actual permission decision before capture. This does not create
consent automatically. No personal recording or private receipt is added to Git or CI.

Optional private `PM_DEMO_LIVE_NAME` supplies an explicit display alias for that exact live
capture ID in the hosted session, unit roster and resident heading. It never rewrites patient
IDs, stored references, history, given-name preferences, consent or fictional fixture names.
Other assigned residents retain their labels; RLS still determines the roster before aliasing.

The personal screen starts in check-in mode. An explicit "Enroll rested baseline" button marks
fresh recordings `is_baseline=true`; "Start check-ins" restores `false`. Both use live mode and
the same browser/device identity, avoiding runner-specific device defaults. The marking is
snapshotted when capture begins; mode controls are disabled during capture/upload. Record five
distinct rested takes. The displayed saved-take count covers usable successful receipts from
this page visit only; it is not a persisted enrollment total or proof of baseline eligibility.
The actual engine response remains authoritative about eligible prior checks and enrolling.

"Record another demo check" starts a fresh microphone capture. The existing checks API already
permits repeated submissions: no once-daily server gate, timestamp override, scoring override,
day advance, fabricated context or reset is introduced. Baseline uploads also remain genuine
measurements. A normal result is valid; no outcome is forced. Personal-demo uploads do not
automatically retry and do not expose resend after an ambiguous error, because an accepted
request with a lost response could otherwise create an extra baseline take. Inspect nurse
history before a new attempt after such an error.

The nurse screen polls the authorized volunteer overview and profile every two seconds while
visible. It shows only the actual latest voice assessment, its eligible prior-baseline count,
measurements, timestamp and history link. Read failure clears the displayed result and offers
retry. Recording starts only on a phone tap. Ordinary unit pages retain ten-second polling and
the separate capture section. Speech processing/commit and optional drafting precede readback,
so a two-second polling interval is not an end-to-end latency guarantee.

No endpoint, schema, threshold, escalation budget or provider contract changes. The hosted
operator must retain the dedicated capture identity's no-escalate configuration and existing
volumes. Deploy the reviewed frontend, then verify the same speaker/phone's five baseline takes,
one usable genuine live result and nurse readback. Physical iPhone/Android codec/microphone,
hosted processing time and actual personal enrollment cannot be established by synthetic tests.
Rollback restores the previous frontend; it does not delete recordings or change stored history.

Compatibility with Danny's overnight polish (PR126, deployed `4bf714c`): preserve the single
shared navigation disclosure, network-recovery copy, motion unknown handling and visual fixes.
Personal recorder/overview mode adapts that same disclosure to describe actual volunteer voice
analysis and unavailable-baseline states. The ordinary shared disclosure distinguishes fictional
residents from live volunteer records; archived handoff keeps its authored-scenario disclosure.
Personal mode controls use the shared secondary-button styling.
