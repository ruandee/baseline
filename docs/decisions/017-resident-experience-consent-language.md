# 017: Recorded consent and a score-free PSW check workflow

Status: accepted implementation contract (Dee's 17 October 2026 handoff); real-device and
nontechnical-tester acceptance remains open. Replaces the earlier proposal in this file.

## Decisions

Consent is append-only per resident and scope (`voice_check` or `vox_encounter`). No row is
`unknown`, never implicit agreement. Resident and substitute decision-maker decisions are
recorded by an assigned nurse; SDM decisions require an opaque `sdm_reference`. An importer
may write explicit `synthetic_fixture` decisions. PSWs cannot read the consent record or
write decisions; they see only effective consent state in the due list. A resident may
withdraw at any time through the nurse workflow. Withdrawal applies to the next check.
Optional `expires_at = null` means no expiry. Latest recorded decision wins; a granted row
whose expiry has passed resolves to `expired`. Device timestamps never determine consent.

`POST /v1/patients/{id}/consents` appends a decision; `GET .../consent?scope=voice_check`
returns its effective view, not the SDM pointer or free-text note. Consent and skip tables
have forced RLS, composite tenant/patient/recorder foreign keys and SELECT/INSERT grants
only. There is no migration backfill. `grant_fixture_consent` is an explicit synthetic
setup helper and inserts only if that scope has no row, preserving later withdrawals on
reload. Seeds and the synthetic cohort loader call it deliberately.

Check submission authorizes the actor first, then checks consent before decode or ASR.
Blocked consent is **403 `consent_required`**, with a separately committed
`check_blocked_consent/denied` audit. No check is stored. `store_check` reauthorizes and
rechecks consent under the shared tenant-budget then patient lock. Consent writers take
the same patient lock. A withdrawal during processing therefore prevents publication;
assignment revocation prevents publication too. All capture modes require consent.
Vox integration must use its own `vox_encounter` scope in addition to its request flag;
that integration is on the separate Vox branch, not silently supplied by voice consent.

## PSW boundary

A separate `psw` assignment permits only the score-free due workflow, resident-mode check
submission and skip logging. It grants no general record, watchlist, overview, evidence,
verdict or SBAR access. Check receipts contain only `check_id`, `ts`, `usable`; enrollment
and live/runner submissions are rejected for PSWs. Nurses retain the full check result.

`GET /v1/checks/due` returns assigned resident names, effective consent state, last check
time, skipped-today state and `due`/`done`/`skipped`/`consent_needed`, using the configured
local shift timezone for midnight. No assessment, feature, score or evidence is included.
`observation_helped` is null (unknown): source submitter attribution does not yet exist.
The UI displays the message only for a future server-computed exact `true`.

`POST /v1/patients/{id}/checks/skips` appends one of `declined`, `asleep`, `unwell`,
`not_available`, `other` with optional device time. Skipping is not consent withdrawal.
A blocked or unconsented resident can still be skipped. Skipping during microphone
permission or recording discards capture; late upload outcomes cannot restart the flow.

Scoring a PSW check needs clinical inputs internally. Ordinary PSW RLS reads of sources,
context tags, voice checks and assessments return no rows. The trusted server enters a
transaction-local, exact-patient scoring context only after authorization, consent and
admission locks, and clears it before returning. RLS also checks active assignment, tenant
and patient. The original actor is preserved for audit. This uses the same private-server
trust boundary as `pm.actor`/`pm.tenant`: database runtime credentials and context setters
are never exposed to API clients. No admin connection is used for scoring. Two narrowly
scoped security-definer aggregates expose only authorized last-check time and the internal
tenant escalation counter, with fixed search paths and an asserted BYPASSRLS migration owner.

## Browser and demo contracts

The `/check` landing remains the PSW due list. Resident bootstrap requests the separate
PSW demo token and receives no nurse token in that response. Hosted resident mode fails
closed if `PM_DEMO_PSW_TOKEN` is missing; local setup creates a dedicated PSW principal.
The public synthetic demo's nurse session remains intentionally available separately;
production authentication remains out of scope.

Device IDs use an explicit `?device=` override, `runner-phone` for runner mode, otherwise
an ID persisted per browser and mode in localStorage. Blocked storage uses `check-page`.
A missing assessment is shown as unavailable, never within-normal. Live results honor
`over_budget` and the server's suggested-action label.

## Remaining gates

The resident UI supports only the existing English `count20-days-v1` protocol. Per-resident
language metadata, other ASR/on-script protocols and check-linked language changes remain
unimplemented; falling back in the UI does not claim multilingual support. Source-submitter
attribution and ?Your observation helped? also remain open. The nontechnical tester, phone
browser, accessibility and real-audio acceptance gates are unrun. Automated synthetic tests
are engineering evidence, not clinical validation or consent for any real person.
