# 026: Run hosted KAZE scheduling and retention in its own tenant

Status: implemented engineering contract (BL-26; real-phone and real-SMS acceptance open).

The previous hosted worker called ingestion directly for tenant 0, bypassing the generic
worker's scheduler and retention loop. Even after BL-26/27 integration, a hosted deployment
could therefore neither advance KAZE sessions nor perform their required 24-hour deletion.

Both CLI and hosted workers now call `worker.run_worker`. It runs retention at startup and
every 60 seconds, scheduling at startup and every 15 seconds, between ingestion passes.
Compose adds a separate `kaze-worker`, with no admin URL, running as `kaze-demo/service` in
`kaze-demo`. The resident worker keeps its tenant-0 importer identity; neither worker broadens
tenant scope. Existing scheduler timing, sender configuration and held ADR 018 questions stay
unchanged. The default sender is offline logging, with no real SMS acceptance claimed.

An explicit `kaze-bootstrap` setup service provisions two fictional self-custody people and
their nurse service assignment. It creates no contacts, sessions or consent by default.
`--grant-fixture-consent` deliberately grants synthetic `voice_check` consent only where no
decision exists, preserving a later withdrawal or decline. It is never a real-person consent
workflow. Hosted setup does not create a session or send a message.

Bootstrap writes owner-only person credentials to the ignored `demo_artifacts` volume at
`/app/artifacts/kaze-demo/session.json`; its service token is omitted. `--json` optionally
emits only the first person's token and patient ID for private command substitution. The
startup helper feeds these to `prepare_deployment kaze-credentials` through stdin and updates
`PM_DEMO_KAZE_TOKEN`/`PM_DEMO_KAZE_PATIENT_ID` without printing them. Nurse and PSW credentials
remain separate. Refresh repeats provisioning and token creation without resetting data,
reactivating revoked assignments, or replacing consent decisions.

Unit tests exercise the actual hosted dispatch, interval cadence, private credential writing
and role separation. Real-DB integration tests exercise contact-free bootstrap, explicit
fixture consent, preserved withdrawal, tenant isolation, scheduler advancement and retention
through the actual hosted entrypoint under the runtime role. Image smoke checks default unknown
consent, no armed sessions, cross-tenant refusal and both running workers. No API contract or
migration is added by this integration.
