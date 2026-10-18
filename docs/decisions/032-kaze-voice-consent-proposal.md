# 032: Proposed explicit KAZE voice-permission workflow

Status: proposed; user decision required. No authorization change is implemented by this document.

## Current blocker

The KAZE person has an importer assignment for self-custody (decision018), not a nurse
assignment. Default bootstrap records no standing voice permission. The `/out` checkbox
acknowledges session setup but does not append a `voice_check` consent decision. Sessions can
therefore arm, then their baseline uploads return `403 consent_required`. The current nonfixture
consent endpoint and RLS allow an assigned nurse to record resident/SDM decisions.

`--grant-fixture-consent` is only for authored fictional fixtures. It must not substitute for a
real participant's decision. The service/nurse token must not be exported into the person UI.

The local Claude handoff explicitly says ADR018 questions1–6 are on hold. Their numbered text
is absent from the committed ADR018, so this proposal does not assume the new authorization
decision is already approved.

## Option A: narrowly scoped self-custody permission

Use the same safety-tenant, active assigned-importer custody boundary that already authorizes
arming/ending that person's sessions. Do not infer ownership by comparing principal and patient
UUIDs. Permit that identity to append only `scope=voice_check`, `decided_by=resident`, for its
authorized safety patient. It may explicitly grant, decline or withdraw its own permission.
This grants no SDM, other-consent-scope, resident-tenant or PSW consent-writing capability.

Implement runtime authorization and forced-RLS checks together in a new migration after014;
never edit applied007/011. Recheck authorization under the patient lock. Keep the existing
unknown/expired/withdrawn gate before processing and at check admission.

Add a distinct stored-voice-permission view/form to `/out`: current effective state, explicit
decision and an initially unticked confirmation. No automatic grant on arm, checkbox change,
bootstrap, reset or page load. Explain that this standing permission persists until withdrawn
or its recorded expiry; arming/ending a session does not grant/revoke it. No new expiry default
or session-retention policy is selected here. Preflight before microphone access and upload;
discard pending capture after withdrawal or patient/page changes.

Required tests: allowed explicit self decision; absent/foreign/revoked/other-tenant custody,
resident-tenant importer, PSW, SDM and other scopes denied; no nurse/service credential fallback;
unknown/withdrawn permission prevents microphone access and server decoding; withdrawal during
processing prevents publication; arm/end does not change permission; no real SMS in tests.

## Option B: retain nurse-only recording

Keep current authorization unchanged. Provide a separately authenticated, assigned human care
operator workflow to record the participant's actual decision before capture. Do not expose the
worker identity or use fictional fixture consent for a real participant. This requires choosing
and provisioning that operator workflow; the current person-only `/out` bootstrap cannot do it.

## Unchanged gates

Neither option validates audio, phone compatibility, SMS delivery or clinical use. Held KAZE
ladder/product-policy questions and Vox prompt switching remain untouched. Real contacts,
recordings and two-phone acceptance still require their own evidence.
