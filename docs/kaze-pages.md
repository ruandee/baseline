# Synthetic Baseline Out pages

`/out` arms a session and records its three usable baseline clips, then check-ins. The form
collects one or two contacts, a local-clock end time, interval (45 minutes by default), session
explainers and whether contact escalation is enabled. The server validates all fields and
enforces stored voice consent independently of the page checkbox. Only explicitly seeded
synthetic fixture consent is created by setup; rerunning setup never replaces a withdrawal.

Run `uv run python -m scripts.kaze_demo` once against the migrated synthetic services. It writes
short-lived identities to ignored `artifacts/kaze-demo/session.json`, never stdout. Choose one
person and configure `PM_DEMO_KAZE_TOKEN` and `PM_DEMO_KAZE_PATIENT_ID` in the server environment
(the latter is that person's patient_id). Do not paste tokens into URLs, browser storage, Git or
logs. Restart the serving process. This follows the existing demo bootstrap contract, not
production authentication; anyone admitted to the synthetic demo origin can request its demo
identity. Public-host access-control choices remain on hold.

The same-origin `/demo/session` request uses `X-PM-Role: kaze`. It returns only that configured
self-custody importer token and that person's roster row after runtime tenant/patient/safety
authorization; missing configuration fails closed, with no nurse-token fallback. The hosted
environment must supply those two variables separately; the page does not auto-seed or mint a
more privileged token. `PM_DEMO_TOKEN` remains necessary for the ordinary hosted shell.

The page obtains microphone access only on a tap. Opt-in location is requested separately,
after recording and only while the session is still open. Denial continues without coordinates.
The recorder rechecks server state before microphone access and publication and cancels pending
permission, capture and location callbacks on page exit, end or clock expiry. Server admission
remains authoritative. It never attaches location to a non-session check. Raw session audio is
removed by the upload handler regardless of debug retention.

`/out/session/{id}` shows the session's checks, trigger reasons, actual delivery outcomes,
acknowledgements and time from first contact escalation attempt to acknowledgement per episode.
This clock includes logged or failed attempts and does not imply a text was sent or delivered.
Coordinates and raw acknowledgement links are redacted. A logged event is labelled **no SMS sent**; it is never
presented as successful delivery. The person page also provides the timeline and an end control.

Countdowns use server next_due_at. Due and later nudge signals use an on-page vibration and
short sound where the browser permits; keep the page open. Background push delivery is not
implemented, and browsers may suppress sound without interaction. Backend timing stays at
2.5 minutes overdue for the second nudge, 5 minutes for first contact escalation, then 10 minutes
per further level. A one-minute check interval does not shorten those delays. A 45-second
presentation needs an honestly labelled previously recorded/staged session or a separately
approved timing plan; this change does not invent one.

Acceptance still requires real phone microphone/geolocation behavior, the two-phone actual SMS
and acknowledgement loop, retention verification and two rehearsals. Real recordings remain on
hold. Synthetic fake-clock/mic tests are not real-audio acceptance. Loud-venue arm context
lowers only the backend SNR threshold by 3 dB after session authorization; other quality gates
remain unchanged. The open session view asks users to step outside to answer somewhere quiet.
ADR018 questions and Vox prompt-switching decisions remain on hold.
