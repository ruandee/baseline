# 035: Phone-to-nurse presentation rooms

Date: 2026-10-18 UTC. Status: accepted implementation direction for BL-17/18/19.

The user replaces the one-tab, three-day presentation in decision034 with two fictional residents
played by a runner and Dee. Each participant must record on their own phone, submit, and have a
receipt arrive on the nurse screen. The nurse adds exertion context for the runner; Dee submits
twice to demonstrate Watch followed by Escalate. These are presentation fixtures, not findings
computed from the recordings. Keep the small visible "Demo scenario" disclosure and expandable
explanation of the authored baselines/findings; do not claim detected exertion.

`/unit?demo=handoff` creates a temporary room using the existing authenticated demo nurse
identity and current membership. The room provides separate random bearer capabilities for the
nurse, runner and second resident. Resident links carry only their capture capability in a URL
fragment. Nurse links/capabilities stay private. Capture capabilities cannot read the dashboard,
add context, delete rooms or authorize any ordinary patient API. Existing Host/Origin/JSON/body
guards apply. Internal presentation routes `/demo/handoff...` are excluded from clinical OpenAPI.

Real audio stays on the phone for playback and is discarded after successful submission or
navigation. Only a UUID idempotency key and elapsed duration (0–30 s) are sent. No audio, features,
speaker identity, location or provider requests are uploaded. A server-received timestamp is
recorded. Nurse polling every two seconds shows the receipt; repeated request IDs cannot advance
the scenario twice, and mismatched retries fail. The runner can submit once, Dee twice.

Runner: receipt -> Watch -> nurse explicitly adds exertion -> Explained. Dee: first receipt ->
Watch; second receipt -> Escalate with fictional matching changes within24h and fused score3.2.
The Run4AT control opens review/handoff guidance; no external alert or completed assessment is
created. No real dates, patient histories, clinical assessments, baseline enrollment, consent or
escalation budgets are modified. The supplied baseline never stands in for a measured personal
baseline on the real engine path.

Rooms live in one bounded, locked process-local store (128 rooms, fixed two-hour TTL), appropriate
only to the existing single-process synthetic host. Server restart loses rooms; multi-worker or
multi-instance deployment is unsupported for this presentation and needs a shared store first.
Expired/deleted rooms cannot be revived by a phone submission. Reset deletes the old room and
creates fresh links. Nurse reload uses its fragment capability to restore the existing room;
localStorage is unnecessary. `/check?mode=live&demo=days` now opens the replacement nurse setup;
the old one-tab presentation remains explicitly reachable only with `demo=legacy-days`.

Validation must cover independent resident progression, capability boundaries, expiry, reset,
idempotent/concurrent retries, input limits, real multi-tab browser capture, microphone failures,
no clinical API writes/audio uploads and phone layout. Physical-device acceptance and presenter
rehearsal remain separate from CI and headless synthetic-microphone evidence.
