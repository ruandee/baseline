# 018: KAZE safety-session model, ladder states and endpoints

Status: proposed (17 Oct 2026, BL-25, issue #27). This is the integration contract for BL-26
(scheduler, #28), BL-27 (SMS and acknowledgement, #29) and BL-28 (pages, #30). Changes to field
names, states or transitions need an amendment here before dependent code relies on them.

## Problem

`docs/06-baseline.md` sketches KAZE tables in a "migration 004" that no longer exists (004 is the
context-tag purge, 005 is BL-10's note-context runs). The sketch keeps contacts in a jsonb column,
stores raw acknowledgement tokens, has no ladder level or due time for a scheduler to act on, and
gives no way for the public `/ack/{token}` route (no bearer identity) to write under RLS. Location
and session check-ins must never be visible across tenant, patient or session, and must be deleted
24 h after a session ends, while `voice_checks` stays append-only for the runtime role.

## Decision

### Tenancy and roles

- Sessions exist only in tenants with `tenants.safety_mode = true` (the separate `kaze-demo`
  tenant created by `scripts/kaze_demo.py`). The insert policy checks `pm_safety_tenant()`, so a
  resident tenant can never hold a session, contact or session check.
- The person going out is a `patients` row in that tenant and holds an **importer** assignment on
  their own row (self-custody). Only an importer (`pm_access(patient, true)`) may arm or end a
  session. This also satisfies `care_gate`, so check-ins reuse `POST /checks` unchanged.
- A `kaze-service` principal is assigned **nurse** on every KAZE person. BL-26/BL-27 run the worker
  as that principal: it can read sessions/contacts/checks and write escalation events and ladder
  state, but cannot arm or end a session.
- Denials are 404 (`not_found`), as everywhere else.

### Tables (migration 006, `006_safety_sessions.sql`)

All three new tables carry `tenant_id, patient_id`, composite FKs to `patients`, and forced RLS.

`safety_sessions` (PK `tenant_id, patient_id, id`)

| Column | Type | Meaning |
| --- | --- | --- |
| `display_name` | text 1–40 | Name used in texts ("{name} asked us to check on them…") |
| `status` | text | `arming`, `active`, `escalating`, `acknowledged`, `ended` (see ladder) |
| `created_at` | timestamptz | Arm request time (server clock) |
| `activated_at` | timestamptz null | When the 3rd usable baseline clip arrived |
| `ends_at` | timestamptz | Planned end; `created_at < ends_at <= created_at + 24 h` |
| `interval_min` | int 1–180, default 45 | Check-in interval; demo uses 1 |
| `context_tags` | text[] ⊆ {`exertion`,`loud_venue`} | Explainers declared at arm time |
| `escalation_enabled` | bool, default true | false: nudges only, never SMS |
| `baseline_required` | int, 3 | Usable baseline clips needed to activate |
| `next_due_at` | timestamptz null | Next check-in due; null while arming or ended |
| `last_checkin_at` | timestamptz null | Server time of the last usable session check-in |
| `ladder_level` | int 0–4, default 0 | Highest ladder level executed in the current episode |
| `episode` | int, default 0 | Incremented by BL-26 each time a new overdue/change episode starts |
| `ladder_trigger` | text null | `missed_checkin` or `speech_change` for the current episode |
| `acknowledged_at` | timestamptz null | Time of the ack that moved the session to `acknowledged` |
| `ended_at` | timestamptz null | Set on end or expiry |
| `end_reason` | text null | `user` or `expired` |
| `delete_after` | timestamptz null | `ended_at + 24 h`; the retention job deletes the session then |

At most one non-ended session per patient (partial unique index); a second arm is 409
`session_open`.

`safety_contacts` (PK `tenant_id, patient_id, session_id, contact_index`): `contact_index` 1 or 2,
`name` 1–40 chars, `phone_e164` (`^\+[1-9][0-9]{7,14}$`). FK to the session, so a contact cannot
point at another person's session. Read by the care team; inserted only with the session.

`escalation_events` (PK `tenant_id, patient_id, id`)

| Column | Type | Meaning |
| --- | --- | --- |
| `session_id` | uuid | FK `(tenant_id, patient_id, session_id)` → session |
| `episode` | int | Session episode this step belongs to |
| `level` | int 1–4 | Ladder level executed |
| `trigger` | text | `missed_checkin` or `speech_change` |
| `channel` | text | `nudge` (level 1, no contact) or `sms` (levels 2–4, one row per contact) |
| `contact_index` | int null | FK to `safety_contacts`; required for `sms`, null for `nudge` |
| `sent_at` | timestamptz | Server time |
| `delivery` | text | `pending`, `logged` (stub sender), `sent`, `failed` |
| `message` | text null | Text as sent, with the ack link replaced by `[ack link]` |
| `ack_token_hash` | bytea null, unique | SHA-256 of the ack token; the raw token is never stored |
| `ack_expires_at` | timestamptz null | Token expiry (BL-27 chooses; at most session `delete_after`) |
| `ack_at` | timestamptz null | When this link was tapped |

`UNIQUE (tenant_id, patient_id, session_id, episode, level, contact_index) NULLS NOT DISTINCT`
makes scheduler passes idempotent: a duplicate pass inserting the same step conflicts.

`voice_checks` gains `session_id`, `lat`, `lon`, `accuracy_m`. Location requires a session,
`lat`/`lon` come together, ranges are checked, and `(tenant_id, patient_id, session_id)` is a FK to
the session, so a check cannot attach to another person's session.

### Ladder states

| Status | `ladder_level` | Meaning | Who moves it |
| --- | --- | --- | --- |
| `arming` | 0 | Collecting baseline; no timer, no ladder | BL-25 |
| `active` | 0 | Timer running; check due at `next_due_at` (level 0 = on-page buzz, client side) | BL-25 activates, BL-26 resets |
| `active` | 1 | 2.5 min overdue: second nudge recorded (`channel='nudge'`) | BL-26 |
| `escalating` | 2 | 5 min overdue or speech-change trigger: SMS to contact 1 | BL-26 + BL-27 |
| `escalating` | 3 | 10 min after level 2, no ack: SMS to contact 2 (contact 1 again if only one) | BL-26 + BL-27 |
| `escalating` | 4 | 10 min after level 3, no ack: SMS to all contacts, "If you can't reach them, call 911." | BL-26 + BL-27 |
| `acknowledged` | frozen | A contact tapped a current-episode link; no further SMS | BL-27 via `pm_acknowledge_escalation` |
| `ended` | frozen | Terminal; `end_reason` `user` or `expired` | BL-25 end endpoint, retention job |

Transitions:

- `arming → active`: the 3rd usable `is_baseline` session check (mode `live`). Sets
  `activated_at`, `next_due_at = activated_at + interval_min`. Unusable clips do not count.
- `active/escalating/acknowledged → active`: a usable session check-in whose change status is not
  `change`/`provisional` with no session explainer (BL-26). Resets `ladder_level = 0`,
  `ladder_trigger = null`, `next_due_at = check ts + interval_min`. An unusable clip never resets.
- `active → active (level 1)`, `active → escalating (2)`, `escalating (2→3→4)`: BL-26 only, each step
  inserting its `escalation_events` row(s). The first step after a reset (from `ladder_level = 0`)
  increments `episode` in the same update. `escalation_enabled = false` caps the ladder at level 1.
- `escalating → acknowledged`: `pm_acknowledge_escalation(sha256(token))` when the token is
  unexpired, its event's `episode` equals the session's and the session is `escalating`. An ack for
  an old episode or non-escalating session is recorded on the event but changes no state.
- any non-ended → `ended`: `POST …/end` (`user`) or `ends_at` passing (`expired`, applied by the
  retention job and by BL-26). Sets `ended_at`, `delete_after = ended_at + 24 h`, clears
  `next_due_at`. Ending is idempotent.
- Nothing leaves `ended`. The ladder never auto-dials anyone.

### Endpoints (bearer auth; 404 on any scope failure)

- `POST /v1/patients/{id}/sessions` (importer, safety tenant) body
  `{display_name, ends_at, interval_min=45, contacts: [{name, phone_e164}] (1–2),
  context_tags: [] , escalation_enabled: true}`; optional `Idempotency-Key`. 201 → session in
  `arming`. 409 `session_open`, 422 `invalid_request` (`ends_at` in the past, before one interval, or
  more than 24 h ahead).
- `GET /v1/patients/{id}/sessions` (care team): the person's sessions, newest first.
- `GET /v1/patients/{id}/sessions/{sid}` (care team): session fields, `baseline: {required, usable}`,
  contacts as `{contact_index, name, phone_masked}`, `checks: [{id, ts, usable, is_baseline,
  change_status, has_location}]` and `escalations: [{id, episode, level, trigger, channel,
  contact_index, sent_at, delivery, message, ack_at}]`. Raw phone numbers, coordinates and token
  hashes are never returned.
- `POST /v1/patients/{id}/sessions/{sid}/end` (importer) body `{}` → 200 ended session.
- `POST /v1/patients/{id}/checks` adds optional form fields `session_id`, `lat`, `lon`,
  `accuracy_m`. With a session: mode must be `live`; `arming` takes only `is_baseline=true`, other
  open states only `is_baseline=false` (422 `invalid_request`); `ended` is 409 `session_ended`;
  unknown/foreign session is 404. Session checks are scored only against the same session's history
  (tonight's baseline), and checks outside a session never use session clips. Session check-ins
  never go to a model provider for SBAR drafting. The response gains
  `session: {id, status, baseline_required, baseline_usable, next_due_at}`.
- `GET /ack/{token}` is BL-27's public route; it calls `pm_acknowledge_escalation`.

### Retention

`pm_retire_safety_sessions()` (SECURITY DEFINER, scoped to `pm_tenant()`, any active member) marks
sessions past `ends_at` as `ended/expired`, then deletes every session whose `delete_after` passed,
with its checks (and therefore locations), their assessments, contacts and events, writing one
audit row per deleted session. The worker loop calls it at most once a minute. `voice_checks`
stays append-only for the runtime role: no DELETE grant is added.

### Interfaces for dependent tickets

- BL-26 reads open sessions (`status IN ('active','escalating')`, `next_due_at`) as `kaze-service`
  and updates `ladder_level`, `ladder_trigger`, `episode`, `next_due_at`, `status` under row lock
  (`SELECT … FOR UPDATE`), taking the patient advisory lock (`lock_patient`) first, as check
  admission does. Last known location for a text: latest session check with `lat`.
- BL-27 generates tokens with `secrets.token_urlsafe(32)`, stores only `sha256` in
  `ack_token_hash`, renders the fixed neutral text from `docs/06-baseline.md`, and never sends real
  SMS in CI. `/ack/{token}` hashes the token and calls `pm_acknowledge_escalation(hash)`, which
  returns `acknowledged`, `recorded` or `invalid` and nothing else.
- BL-28 polls `GET …/sessions/{sid}` and uploads clips with `session_id` and location.

## Consequences

- KAZE data never shares a tenant with residents; RLS and the safety-tenant check enforce that.
- Activation is the only ladder logic in BL-25; timing and escalation remain BL-26's.
- Migration 006 chains directly off BL-10's 005 (`note_context_runs`), so alembic has one head.
- Not done here: scheduler, SMS, ack route, pages, `loud_venue` quality tolerance, and integrated
  acceptance after the PointClickCare path reaches BL-13.
