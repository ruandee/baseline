# 031: Explicit resident counting language and given name

BL-31 requires the resident's language and a warm first-name close. A roster display label
does not establish either: honorifics, surnames and anonymized labels must never be parsed into
a given name. The shipped ASR/on-script pipeline supports only English `count20-days-v1`.
This change adds configuration and fail-closed admission, not translation or new ASR support.

Migration 014, following explicit authorship 013, adds `resident_check_profiles` under forced
tenant/patient RLS. Assigned check writers can read its score-free projection. Assigned care
roles can replace the explicit nullable `first_name` and `preferred_locale` through
`GET/PUT /v1/patients/{id}/check-profile`; writes take the patient lock and mint a new version
UUID even if the language remains unchanged. The full explicitly supplied given name is kept.
Null means unconfigured; other syntactically valid locale preferences remain unsupported.
The protocol registry recognizes exactly `en`, deriving `protocol_locale=en` and
`prompt_version=count20-days-v1`. Regional tags are not silently normalized into support.

The PSW due list includes the same score-free `check_profile` and adds
`status=language_unavailable` when consent is granted but the profile cannot admit a check.
The direct resident screen reads the authorized profile rather than trusting bootstrap roster
names or a URL language. Missing/unsupported profiles and conflicting `?lang=` requests show
an explicit staff-help state with no record or spoken-prompt control. The English spoken prompt
remains optional browser speech synthesis; no device voice or clinical validation is promised.
The close uses the full explicit first name, or simply “Thank you.” without guessing.

Non-session counting admission checks support and any submitted `profile_version` /
`protocol_locale` before decode/ASR. Legacy clients may omit these fields, but the server still
requires an explicit supported resident profile. The server snapshots that version and rechecks
it under the same admission/patient locks as check storage. A changed profile during processing,
including English-to-English edits, returns 409 `check_profile_changed` and stores no check.
Unconfigured/unsupported language returns 409 `check_language_unavailable`. Existing authorization
and consent gates run first. The resident UI also rechecks the version before microphone access.

New admitted counting checks append `voice_check_profiles`: profile version, declared locale,
protocol and explicit first name, linked by the full composite voice-check key. Insert validation
binds the snapshot to that check and the admitted current profile. The sidecar is care-readable
and append-only for the runtime; it is deleted with capture retention/reset. No historical
voice-check row, source text or canonical fixture hash is rewritten. Baselines remain segregated
by registered prompt version. Profile changes do not change clinical source revisions or verdicts.

Known synthetic setup paths explicitly seed English profiles with no inferred given name and
`ON CONFLICT DO NOTHING`; existing supported, unsupported and explicitly unconfigured choices
survive reloads. New API-created residents receive no inferred profile or consent. Existing
volunteers need an explicit care-team configuration. KAZE session admission and the held Vox
free-conversation protocol are unchanged. No translated protocol, language-change explainer,
automatic language detection or baseline mixing is introduced.

Verification covers score-free RLS and role denial, unsupported/missing predecode rejection,
version races, append-only provenance, preserved seed choices, explicit multiword first names,
URL mismatch and PSW blocking, plus actual-shell phone browser screenshots without recording.
