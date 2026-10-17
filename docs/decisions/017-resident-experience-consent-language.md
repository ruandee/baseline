# 017: Resident check consent and language metadata (proposal)

Status: **proposed, not accepted** (17 Oct 2026, BL-31, issue #33). Nothing in this file is
implemented server-side yet. Migration 007 is reserved for it and will be written only after
Yuhan (BL-17 owner) and Dee agree the contract below on issue #33.

## In plain words

`docs/06-baseline.md` says a resident's voice check is blocked unless consent (or a substitute
decision-maker's consent) is recorded, and that the spoken prompt uses the resident's language.
Today the database has neither: `patients` holds only `external_id` and `revision`, and
`POST /v1/patients/{id}/checks` accepts any clip from a care-team caller. BL-31 adds the
resident-facing page now, but the page cannot enforce consent: a hidden button is not a control.
This proposal puts consent and language on the server, makes missing consent an explicit
`unknown` that blocks the check, and keeps the synthetic fixture path working by writing
consent rows explicitly instead of defaulting them.

## Proposed contract

### 1. Consent records (migration 007, table `resident_consents`)

Append-only, patient-owned, forced RLS, composite `(tenant_id, patient_id)` foreign key to
`patients`, `SELECT, INSERT` only for `pm_runtime` (no `UPDATE`/`DELETE`, so earlier knowledge
is never rewritten).

| Column | Type | Notes |
| --- | --- | --- |
| `tenant_id`, `patient_id`, `id` | uuid | primary key `(tenant_id, patient_id, id)` |
| `scope` | text | `voice_check` now; `vox_encounter` reserved for BL-32 |
| `status` | text | `granted`, `declined`, `withdrawn` |
| `decided_by` | text | `resident`, `substitute_decision_maker`, `synthetic_fixture` |
| `sdm_reference` | text, null | opaque pointer to the facility's SDM record; never a name or phone number |
| `effective_from` | timestamptz | event time |
| `expires_at` | timestamptz, null | null means no expiry |
| `recorded_by` | uuid | principal who entered it |
| `recorded_at` | timestamptz | knowledge time, `clock_timestamp()` |
| `note` | text, null | short free text, max 500 chars |

`synthetic_fixture` is accepted only when `PM_ENVIRONMENT=synthetic` (already the only allowed
environment) and only from an `importer` assignment, so the cohort loader and test sandbox can
grant consent on purpose. Rows with `decided_by=substitute_decision_maker` require
`sdm_reference`.

**Effective consent** for a scope at time `t` is the latest row by `recorded_at` whose
`effective_from <= t`. It resolves to one of:

| State | Meaning | Check allowed |
| --- | --- | --- |
| `granted` | latest row granted and not expired | yes |
| `declined` | latest row declined | no |
| `withdrawn` | latest row withdrawn | no |
| `expired` | latest row granted but `expires_at <= t` | no |
| `unknown` | no row at all | **no** |

Missing consent is `unknown`, never `granted`. There is no backfill in migration 007: existing
synthetic patients get `unknown` until the loader (BL-14) or reset (BL-21) writes their rows.

### 2. Enforcement in `POST /v1/patients/{id}/checks`

- Checked in the first `care_gate` transaction, **before** the audio is decoded or sent to
  Whisper, and again inside `store_check` (decoding takes seconds; consent can be withdrawn
  meanwhile).
- Not `granted` returns **409 `consent_required`** with `consent_state` in the problem body.
  Nothing is stored, the audio temp directory is removed, and an audit row
  `check_blocked_consent` is written. 404 stays reserved for "no access", so a caller with
  care access learns the consent state but a caller without access learns nothing.
- `mode=live` and `mode=runner` follow the same rule; the runner and live-demo speaker get
  explicit `resident` consent rows in the demo reset.
- BL-32 (Vox) keeps its own per-request `consent: true` field **and** requires `granted`
  `vox_encounter` consent here; the request flag alone is not enough.

### 3. Language

- `resident_check_settings` (same migration, same RLS rules, append-only): `preferred_language`
  (BCP 47, e.g. `en-CA`), `recorded_by`, `recorded_at`. Latest row wins. No row means
  `null` (unknown), never assumed English.
- `POST /checks` gains an optional form field `language` (BCP 47). It is stored on
  `voice_checks.language` (nullable; existing rows stay null = unknown).
- **Prompt versions are per language.** `count20-days-v1` is the English protocol, with English
  ASR (`language="en"`) and the English on-script check. A resident who counts in French
  against that prompt is `off_script`, and mixing languages would corrupt the baseline.
  Another language needs its own `prompt_version` (e.g. `count20-days-v1-fr`), its own ASR
  language and word list, and the existing engine rule (baselines only use the same
  `prompt_version`) keeps the histories apart. Until those exist the server rejects a
  `language` whose primary subtag has no registered prompt with 422 `unsupported_language`.
- With check-level language stored, the check-only `language_change` explainer (decision 007)
  can be linked to a specific check instead of staying forbidden.

### 4. Read model for the PSW landing (no scores)

`GET /v1/checks/due` (care-team only, RLS-scoped like the watch list) returns per resident:
`patient_id`, `display_name`, `preferred_name` (open question below), `preferred_language`,
`consent_state`, `last_check_ts`, `skipped_today`, `observation_helped`. It deliberately has
**no** verdict, fused z, feature or sparkline fields, so a PSW device never receives scores.

`observation_helped` is computed server-side for the caller: true when an `escalate`
assessment in the current shift cites a note source whose import was submitted by the calling
principal. Computing it on the server avoids sending other principals' IDs to the browser.
This needs source submitter attribution, which `sources` does not store today; until it does,
the field is always false.

### 5. Skip log

`POST /v1/patients/{id}/checks/skips` with `reason` in `declined`, `asleep`, `unwell`,
`not_available`, `other` and `device_ts`. Audit-style row, care-team only, no audio, no score.
A `declined` skip is not a consent withdrawal; withdrawal goes through the consent API.

### 6. Writing consent and language

`PUT /v1/patients/{id}/consent` and `PUT /v1/patients/{id}/check-settings` append rows; nurse
assignment required (importer for `synthetic_fixture`). Both take `Idempotency-Key`. `GET`
returns the effective state plus history.

## What BL-31 ships before agreement

The page changes only (see `docs/build-status.md`): spoken prompt, large type, listening state,
skip, one-retry rule, warm close, due-now list, no scores in resident mode. The page offers
only languages that have a prompt version (English today), does not claim consent is recorded,
never shows "Your observation helped" (the field does not exist yet), and builds the due-now
list from `/v1/watchlist` by projecting only name and last-check time before anything renders.
That projection hides scores from the screen but not from the network; the dedicated
`/checks/due` endpoint above is the fix. Skips are not logged server-side yet.

## Open questions for Yuhan and Dee

1. 409 `consent_required` versus 403 or 422 for a blocked check.
2. Should `live` mode (anonymous demo speaker) need a consent row, or a separate demo patient
   with `synthetic_fixture` consent?
3. A `psw` assignment role (record checks and read `/checks/due`, but not the watch list or
   overview) versus reusing `nurse` for the demo.
4. `preferred_name` for "Thank you, {first name}": a column in `resident_check_settings`, or keep
   using the demo session's synthetic names.
5. Expiry policy: should `granted` require `expires_at` (annual review), or allow open-ended?
