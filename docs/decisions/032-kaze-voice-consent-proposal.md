# 032: Explicit KAZE voice-permission workflow

Status: accepted, option A. The user explicitly selected option A on 17 October 2026
(America/Toronto). Migration015 implements the scoped authorization below.

## Prior blocker

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

## Accepted option A: narrowly scoped self-custody permission

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

## Considered alternative B: retain nurse-only recording

Keep current authorization unchanged. Provide a separately authenticated, assigned human care
operator workflow to record the participant's actual decision before capture. Do not expose the
worker identity or use fictional fixture consent for a real participant. This requires choosing
and provisioning that operator workflow; the current person-only `/out` bootstrap cannot do it.

## Unchanged gates

Neither option validates audio, phone compatibility, SMS delivery or clinical use. Held KAZE
ladder/product-policy questions and Vox prompt switching remain untouched. Real contacts,
recordings and two-phone acceptance still require their own evidence.


## Implementation and verification

Migration 015 adds a separate permissive INSERT policy to the existing forced-RLS consent
table. The helper is SECURITY INVOKER and requires the same safety-mode tenant and active
assigned-importer custody as arm/end. Existing nurse/fixture policies and all applied migrations
are unchanged. Runtime authorization repeats under the patient lock before appending the
explicit resident decision. Default bootstrap/reset still does not grant permission.

The standalone `/out` fieldset shows effective standing permission and separate explicit
choices with an initially unticked confirmation. It does not depend on the care-home counting
profile or require a worker/nurse credential. Starting a decision save immediately invalidates
active/pending capture, even while the request is unresolved. A later grant does not restart an
old microphone callback. Capture rechecks permission before microphone access, after permission
resolves, and before upload (including a delayed location response). Page exit and session end
cancel capture. No real SMS or microphone recording is performed by the automated tests.

Deterministic tests cover unknown/default states, explicit decisions, direct runtime-role RLS,
wrong tenant/patient/actor, custody revocation, PSW/SDM/other-scope denial, no UUID-ownership
inference, independent session arm/end, permission withdrawal during processing, pending
microphone/location callbacks and stale callback isolation. Exact-head CI remains required;
physical phones, real contacts and provider delivery retain their separate acceptance gates.
