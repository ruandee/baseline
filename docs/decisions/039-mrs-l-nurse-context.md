# 039: Mrs. L nurse context in the current unit demo

Date: 2026-10-18. BL-19 follow-up; user requests immediate deployment without waiting for full CI.

Expose a confirmed observation form on the authored Mrs. L resident page, enabled by explicit
hosted-session metadata. The hidden-from-OpenAPI hosted endpoint `/demo/residents/{id}/context`
admits only the canonical seeded nurse and Mrs. L patient UUID after ordinary RLS authorization.
It cannot target volunteers, arbitrary patients, another tenant, or a safety session. Existing
same-origin, bearer, payload and deployment guards apply. No credential is returned to the UI.

The existing seeded importer service publishes only this bounded structured observation through
`add_context`; the nurse is not assigned a broader write role. Audit records the requesting nurse
and published source. The source retains the existing system-generated structured-source
attribution; this is not an imported clinical nursing note. A required observation, explicit
confirmation, selected explainer and effective interval replace authored verdict shortcuts.

Under the existing budget/patient admission locks, reject a stale displayed assessment and
require an immutable usable synthetic voice check. The observation must apply at that check's
event time. Publish the source/facts/tag, bump revision and append a reassessment using the
original check ID, timestamp, measured values and history in one transaction. No new recording,
forced Explained verdict or score change occurs. Amplifiers still win. Original assessments
are invalidated under decision015 and their copied prose is scrubbed as usual. The operation is
idempotent; unchanged retries reuse the same key. Recheck nurse authorization before commit.

After success the UI reloads the actual overview and exposes the normal source evidence. A
failure or stale assessment retains the earlier display and reports uncertainty; no success or
Explained result is invented. General `/v1` source/context authorization and contracts remain
unchanged. This is a bounded hosted demonstration, not general nurse-write capability.

The user subsequently renames the three existing hosted scenario records to Alina, Danny and
Yuhan (formerly Mrs. K, Mr. T and Mrs. L). Preserve all UUIDs, assignments, captures, assessment
values and immutable source text. The explanation capability remains bound to the same patient
UUID and uses the current display name. Template Situation headings display that current name;
historical source quotations and stored draft payloads retain their original text. Profile given
names are explicitly updated to the user-supplied names without changing language preferences.
