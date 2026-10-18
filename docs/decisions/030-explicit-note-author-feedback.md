# BL-31: explicit note authorship and private positive feedback

## Decision

An assigned importer may assert a nursing note's exact author principal and role (`nurse` or
`psw`). The author must be active and assigned that role to the same tenant/patient at import.
This is an importer assertion validated against current membership, not proof of historical
professional identity. Names, note wording and the transport actor never imply authorship.
No PSW note-writing route or EHR integration is introduced.

`SourceInput.author_principal_id` is optional. New PSW note attribution requires it; ordinary
legacy notes remain unknown. The model serializer omits only this new field when absent or
null. Every old nullable field, JSON representation, source hash, idempotency hash, fixture
manifest and strict reset-integrity check keeps its prior behavior. Extraction text and exact
source offsets are unchanged. An explicit author changes the immutable version payload, so
conflicting retries remain conflicts rather than retroactive attribution.

Migration 013 follows final 011 and 012. `source_authors` is a plain append-only table with
forced RLS and composite tenant/patient/source and tenant/principal foreign keys. Care-team
roles can read the mapping; assigned importers can insert it with their own assertion identity.
The closed validator checks eligibility before object work. A protected insertion trigger
rechecks live membership, binds the mapping to the exact immutable payload and stamps server
knowledge time. No runtime UPDATE/DELETE or ordinary PSW SELECT is granted. A protected source
purge trigger removes the mapping. Retraction, visibility and supersession retain existing
revision invalidation; no earlier source or assessment snapshot is rewritten.

## Positive feedback boundary

The due-list field is `true | null`, never false. A narrow fixed-search-path definer returns
true only for the current actor's explicitly attributed PSW note cited by exact fact UUID in
the latest eligible resident escalation's reasons or validated SBAR. All other cases remain
unknown. It returns no note text, citation, assessment identifier, reason, verdict or score.
PSW timeline, evidence, source, watch list and assessment access remain denied.

The latest resident assessment ID is selected by a shared SECURITY INVOKER helper used by both
ordinary overview and the closed feedback aggregate. Its eligibility/order matches the prior
overview: current patient revision, not invalidated, no session signal, event time at or before
the cutoff, optional modality, then event/creation/ID order. Ordinary PSW calls still return
null under existing assessment RLS; there is no new scoring context in the due endpoint.

Feedback adds a 24-hour freshness window, which is an engineering limit on the acknowledgement
message only. It does not change verdict policy, interruption budgets or clinical history.
The current latest assessment must actually escalate without budget/profile suppression.
All contributing current/baseline fact and voice citations must still resolve in scope, all
contributing modality events must remain fresh, and all cited context must remain unexpired.
This prevents credit after another contributing RR/motion fact expires without a revision bump.
The exact own-note source must be published by assessment knowledge time, active and not superseded;
its attribution must also predate that assessment. Exact facts and their note context must be
valid at signal event time and remain unexpired now. Own-note facts may retain the extractor's
uncertain/unspecified source-assertion attribution, but absent polarity or another experiencer
can never earn credit. Future events, stale revisions, a newer
watch assessment, expired context, revocation, retraction, supersession and purge withhold the
message. A note merely being present, semantically similar or submitted by the importer does
not earn credit. Existing unknown author mappings are never backfilled by guessing.

## Validation and limits

Tests cover legacy serialization/hash/replay, role/patient/tenant scope, pre-object denial,
immutable payload binding, forced RLS, direct PSW helper calls, exact own citations, clinical
read denials, lifecycle/freshness gates and original overview-selection parity. Unit and CI
results are recorded at the PR's exact head. Only synthetic fixtures are used. No clinical
impact or real EHR authorship validation is claimed.
