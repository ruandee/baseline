# API and behavior contracts

These contracts are normative for the prototype. B02 must encode them as Pydantic models and generated OpenAPI before feature implementation. Prefix all routes with `/v1`. JSON uses snake_case; IDs are UUIDs and timestamps RFC3339 UTC. Require bearer identity except local liveness. Tenant and actor come from authenticated membership, never a trusted request-body field.

## Routes

| Method and route | Request | Success |
| --- | --- | --- |
| POST `/patients` | `external_id` (tenant-unique, 1–128 chars) | 201 `{patient_id}`; admin/importer only |
| POST `/patients/{id}/sources` | SourceInput below; `Idempotency-Key` header | 202 `{job_id, source_version_id, status}` |
| GET `/patients/{id}/jobs/{job_id}` | None | 200 `{status, stage, attempt, error_code, memory_revision}` |
| POST `/patients/{id}/jobs/{job_id}/retry` | Empty object; idempotency header | 202 job; importer only, failed jobs only |
| POST `/patients/{id}/sources/{version}/retract` | `{reason}`; idempotency header | 200 `{memory_revision}`; importer only |
| GET `/patients/{id}/timeline` | `as_of`, `known_at`, `from`, `to`, `cursor`, `limit` (1–100) | 200 `{events, next_cursor, memory_revision, coverage}` |
| POST `/patients/{id}/questions` | `{question, as_of?, known_at?}` | 200 Answer below |
| POST `/patients/{id}/summaries` | `{shift_start, shift_end, known_at?}` | 200 Answer with fixed summary sections; as_of=shift_end |
| GET `/patients/{id}/evidence/{evidence_id}` | None | 200 authorized canonical excerpt with provenance |
| GET `/health/live` | None | 200 process alive, no internals |
| GET `/health/ready` | Internal authorization | 200 dependencies ready or 503 |

`SourceInput`: `{external_document_id, external_version_id, source_system, kind, author_role, author_principal_id?, visibility, recorded_at, effective_from?, effective_to?, supersedes_version_id?, text?, records?}`. Kinds: `nursing_note`, `patient_report`, `observation`, `medication_event`. Exactly one of text (nonempty) or records (nonempty array); text for note/report, records for structured kinds. Record: `{concept, value, unit?, polarity, effective_from?, effective_to?, order_id?, event_type?}`. Medication event types: `ordered`, `administered`, `stopped`, `mentioned`; require order_id for ordered/stopped. Polarity: `present`, `absent`, `uncertain`. `author_role` and visibility are validated against the caller's granted import capabilities. Visibility: `care_team` or `patient_and_care_team`.

Reject future `known_at`, inverted intervals, unsupported content types and cross-patient supersession. A patient ID on the route is canonical; reject conflicting IDs inside source payloads. MVP importers must supply correctly linked IDs. Unknown unit/concept mappings remain explicit unmapped values rather than guessed conversions.

Roles: administrator manages patient records and assignments; importer writes assigned patients' sources; nurse reads assigned patients' care-team evidence; patient reads their own patient-visible evidence. Prototype patient role has read access only; diary contribution arrives in a later milestone. Infrastructure administration alone does not grant clinical read permission.

Question length 1–4,000 characters. Default request deadline 30 seconds and configurable per-principal rate limit, initially 30 generated requests/minute. Rate limit returns 429 with Retry-After. Timeline cursor is opaque, signed and bound to scope/cutoffs/revision; a changed revision returns 409 `cursor_expired`. Stable order: event time (unknown last), source version ID, fact ID.

## Answer shape

```json
{
  "request_id": "uuid",
  "patient_id": "uuid",
  "status": "answered",
  "as_of": "2026-01-02T08:00:00Z",
  "known_at": "2026-01-02T08:00:00Z",
  "memory_revision": 4,
  "claims": [
    {
      "claim_id": "c1",
      "section": "recent_changes",
      "text": "The synthetic note reports improved sleep.",
      "epistemic_status": "documented",
      "evidence_ids": ["uuid"],
      "effective_at": "2026-01-02T06:00:00Z"
    }
  ],
  "evidence": [
    {
      "evidence_id": "uuid",
      "source_version_id": "uuid",
      "source_kind": "nursing_note",
      "author_role": "nurse",
      "recorded_at": "2026-01-02T06:05:00Z",
      "ingested_at": "2026-01-02T06:06:00Z",
      "quote": "Patient reports improved sleep.",
      "start": 0,
      "end": 31
    }
  ],
  "unknowns": [],
  "conflicts": [],
  "coverage": {"index_complete": true, "truncated": false, "degraded_mode": null},
  "versions": {"model": "stub-v1", "prompt": "v1", "retriever": "v1"}
}
```

Illustrative IDs are placeholders; runtime validates UUIDs. Status enum: `answered`, `partial`, `insufficient_evidence`, `conflicting_evidence`. Claim status enum: `documented`, `patient_reported`, `historical`, `uncertain`. Every clinical claim requires at least one valid evidence ID. Unknowns are `{topic, reason}`; reasons include `not_documented`, `unknown_time`, `not_yet_indexed`, `outside_retrieval_window`. Conflicts are `{topic, claim_ids, evidence_ids, resolution: null}`. Do not expose the existence of inaccessible records through coverage fields.

No evidence → empty claims, `insufficient_evidence`, explicit unknown. Conflicting evidence → preserve both assertions and set `conflicting_evidence`, even if other claims are answerable. Pending eligible source jobs → `partial` or `insufficient_evidence` with `index_complete=false`. Unauthorized content is never passed to generation or named in unknowns.

## Failure and consistency rules

Error envelope: `{error: {code, message, request_id, retryable}}`; no stack traces or note content. 400 malformed syntax; 401 invalid identity; 404 missing or unauthorized patient/resource (avoid existence leakage); 409 idempotency conflict, invalid retry state or expired cursor; 413 payload too large; 422 invalid schema/interval; 429 rate limit; 502 invalid model output; 503 unavailable index/dependency; 504 provider timeout.

Read from one published patient revision. Before returning a generated answer, check revision and authorization again; if changed, retry once with new scope/revision, then return 409 `memory_changed`. New authorized pending sources are reflected in coverage. Source corrections require new versions; never overwrite raw text. An empty timeline is a valid 200, but a failed index is not an empty timeline.

API tests must cover role × route × patient ownership, not just happy paths. Citation fetches enforce current permission even when the answer was created earlier.

Implementation additions: administrators manage assignments through `PUT /patients/{id}/assignments`; importers can change source visibility with `PUT .../sources/{version}/visibility` and request active-store erasure with `POST .../sources/{version}/purge`. Those source mutations require idempotency keys; purge returns 202. Unsupported request content types return 415. When retrieved evidence exists but the model selects none, unknown reason is `selection_abstained`, distinct from `not_documented`.


BL-31 explicit care-note attribution (decision 030): assigned importers may supply a same-tenant,
same-patient active `author_principal_id` matching the note's `nurse` or `psw` author role.
PSW authorship requires that explicit principal; no PSW import capability is granted. Omitted
attribution retains exact legacy source serialization and remains unknown. The score-free due
list returns `observation_helped: true` only for an exact own-note citation in a current eligible
fresh escalation; all other cases return null and expose no clinical evidence or score.


Decision032 adds no consent schema or expiry default: the assigned importer custodian in a
safety-mode tenant may append only `scope=voice_check`, `decided_by=resident` decisions through
the existing consent endpoint. Nurse/SDM and explicit synthetic-fixture authorization retain
their existing scope. Session arm/end does not grant or withdraw standing voice permission.
