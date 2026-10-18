# 038: Genuine personal-baseline phone demo

Date: 2026-10-18. Scope: BL-15 follow-up, using existing BL-17/18 APIs.
Status: local implementation; deployment, enrollment and physical-phone rehearsal pending.

The runner is unavailable. Dee requests actual recording, comparison against Dee's own rested
baseline, prompt nurse updates and repeated check-ins within a short demo. This restores the
genuine measurement direction of decision030. Decision036's authored handoff room remains a
separate presentation and is not evidence that recordings were analyzed.

The nurse workspace offers a personal-demo link only for the session's dedicated live capture
identity, outside the scripted cohort. `/check?mode=live&demo=personal&patient=<id>` rejects a
scripted or unrecognized capture identity in the UI. Existing server authorization, counting
profile, current consent and evidence rules remain authoritative. Explicitly configure English
and the volunteer's actual permission decision before capture. This does not create consent or
provision a resident automatically. No personal recording/name is added to Git or CI.

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

`/unit?demo=personal` polls the ordinary authorized watchlist every two seconds while visible;
ordinary unit pages retain ten seconds. Refresh begins after speech processing/commit and any
optional draft work, so this is not a two-second end-to-end latency guarantee. Visibility and
authorization-denial behavior stay unchanged. Capture identities retain their separate section
on the nurse screen, avoiding contamination of the fictional cohort's review order.

No endpoint, schema, threshold, escalation budget or provider contract changes. The hosted
operator must retain the dedicated capture identity's no-escalate configuration and existing
volumes. Deploy the reviewed frontend, then verify the same speaker/phone's five baseline takes,
one usable genuine live result and nurse readback. Physical iPhone/Android codec/microphone,
hosted processing time and actual personal enrollment cannot be established by synthetic tests.
Rollback restores the previous frontend; it does not delete recordings or change stored history.

Compatibility with Danny's overnight polish (PR126, deployed `4bf714c`): preserve the single
shared navigation disclosure, network-recovery copy, motion unknown handling and visual fixes.
Personal recorder/overview mode adapts that same disclosure to describe actual volunteer voice
analysis and unavailable-baseline states; ordinary and authored handoff modes retain their own
wording. Personal mode controls use the shared secondary-button styling.
