# F01: Local synthetic patient workspace

## Decision

Add buildless HTML/CSS/JavaScript in `frontend/`, served by the explicitly launched
`scripts.frontend` development entrypoint on loopback port 8001. This is the user's
requested frontend extension after B11, not a claim that outstanding pilot gates
are complete. No production API contracts or database schema change.

The launcher idempotently loads the existing 12 synthetic profiles into a dedicated
stable demo tenant. Fictional display aliases live in launcher metadata. It assigns
a separate nurse principal to these patients; the browser receives no importer or
administrator identity. The existing authenticated API handles all timeline,
question, summary, and evidence reads. Fixture bootstrap uses admin credentials
only in the CLI launch path, never in a public HTTP handler.

`GET /demo/session` is a development-only session bootstrap returning the display
roster, a short-lived nurse token, and the fixture snapshot. It requires a same-origin
custom header, a loopback client and Host, and rejects cross-origin/Fetch Metadata
requests. Responses are no-store. Tokens are held in JavaScript memory and never
persisted to localStorage or checked-in assets. No CORS broadening is introduced.
Do not deploy or tunnel this server; production identity remains undecided.

## Experience and invariants

Patient search, timeline type filters, pagination, source details, evidence-linked
questions, and UTC shift summaries are functional. Changing patient clears answers
and ignores late responses from the previous patient. Exact source quotes render as
escaped text. Current authorization is checked again on source inspection.
Attribution, historical intervals, unknowns, conflicts, and retrieval limitations
remain visible. No diagnoses, recommendations, or invented demographics are added.
The initial `as_of` is January 3 at 00:00 UTC so authored January 2 records are easy
to explore; `known_at` defaults to the real request time, preserving ingestion time.

## Validation and limits

44 tests pass, including the full existing PostgreSQL/S3 suite and two new frontend
contract tests for local-origin restrictions, read access, unassigned patients,
and denied writes. Browser checks cover live citations, handover generation,
patient switching, abstention, search, type filters and responsive layouts.
The existing Starlette/httpx deprecation warning remains. Real model evaluation,
clinical validation and production deployment were not run. Patient writes and
historical-cutoff controls are not included in this read-only frontend.
