# BL-10: Attributed note context and bounded provider fallback

Notes are untrusted source assertions, never clinical truth. A strict response contains
at most 24 tags from the seven note-only taxonomy entries, each with an exact quotation
of at most 1600 Unicode code points. The server computes offsets against canonical text;
fabricated quotations are dropped. Language changes cannot be resident-wide note tags.
Sentence-wide conservative checks reject negation, hypothetical/historical findings,
other subjects and obvious instruction text, even if a provider omits them from its quote.
Contractions are normalized before the guard. Only positive idioms such as "not herself"
and "didn't finish" are exempted; "did not sleep poorly" remains a negated proposition.
These guards are engineering controls, not a clinically validated language interpreter.

`baseline.llm.request_json` reuses configured compatible/Ollama settings with strict JSON
schema output, no redirects or environment proxies, a 64 KiB input cap, 128 KiB response
cap and 2048-token output cap. Async HTTPX runs under a cancellable 15-second
`asyncio.timeout` covering connection, request, response headers and body together;
the synchronous entry point is for sync route/worker threads. Timeout cancels and closes
network I/O rather than leaving a background request running. Parsing the bounded response
and local scheduling can add local overhead; this is not a strict total API latency claim.
Exceptions contain fixed codes;
provider request/response bodies and credentials are not logged. Stub mode never calls it.
Provider errors/schema failures use deterministic keywords. An empty valid provider result
stays empty. Oversized notes use keywords. Keyword fallback records `extracted_by=structured`
under the existing enum; a durable run marker distinguishes `keyword` from `gemini`.

The worker computes proposed tags outside its publication transaction, then rechecks
authorization, the lease and source lifecycle under the patient lock. Facts, tags, source
publication, marker and revision commit together. Note tags cite the existing attributed
sentence fact; shorter provider quotes have their own exact source offsets. On-demand
extraction never adds facts to an already published source, preserving earlier QA knowledge
snapshots. Consumers must apply context-tag creation time to knowledge cutoffs and continue
joining source lifecycle and visibility; retraction does not erase historical evidence.
Purge deletes quotes from tags/facts; the marker contains only IDs, method and time.

Migration 005 adds `note_context_runs` with forced RLS, composite source ownership and
importer-only inserts/updates. Empty and fallback results count as processed. Normal retries
do not call the provider again. `POST /v1/patients/{id}/notes/extract` requires an assigned
importer, processes at most one active published note and returns counts/methods without
source text. Repeat calls advance a backlog. Explicit `?retry_fallback=true` reconsiders
keyword-completed notes; successful model runs update the marker and append valid tags,
preserving prior assertions and their knowledge times. It does not silently erase fallback
evidence or widen permissions. The response reports `batch_limit=1`. Return counts describe
inserts, not attempted tags. The service reads an authorized source/revision snapshot in a
short transaction, closes it before model work, then reacquires the patient lock in a new
transaction and rechecks authorization, revision, source hash/visibility/publication,
supersession, lifecycle and the completion marker. A changed snapshot discards proposals
without marking the note complete; callers may retry. No patient lock or open transaction
spans network work. Each note's tags, marker and revision publish atomically; publication
also invalidates prior assessments when the BL-11/13 freshness integration is present.

Validation: frozen sync and lint pass. After installing ffmpeg, the Windows unit suite:
182 passed, no skips, 6 slow tests deselected. Added deterministic mocked provider, Unicode,
fabrication, negation, fallback, lifecycle/idempotency, authorization and RLS tests. Docker
is unavailable locally; migrations, DB-backed tests and stub evaluation run through CI.
New regressions exercise contracted/embedded negation, unlocked concurrent source changes,
revision/permission changes during provider work, and cancellation while waiting for
headers and across the combined header/body budget.
No live model calls, patient data or audio validation were performed by this change.
