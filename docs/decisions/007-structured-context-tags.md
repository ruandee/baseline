# 007: Structured context tags are derived in the worker and removed on purge

Status: accepted (17 Oct 2026, BL-09, issue #11).

## In plain words

The structured rules (high-risk medication, fever, `context.*` observations) run inside the
worker's publish transaction, next to fact extraction, so a tag and the facts it quotes appear
together or not at all. `POST /v1/patients/{id}/context` submits an `observation` source through
normal ingestion, then synchronously publishes its canonical text, fact and tag in the same
transaction. The 201 response has resolvable evidence even when no worker is running. The source
job is completed and the patient revision bumped once; replay does neither again.

Both paths build the tag from the same pure rules (`baseline/context.py`) and give it an id derived
from the source span and tag name, so a worker retry cannot duplicate a tag. The endpoint and worker use the same fact-storage
helper; ordinary source imports still publish asynchronously.

## Choices worth knowing

- **Where the drug name is matched.** The spec does not say whether the drug sits in `concept` or
  `value`. The rule checks both, as a whole lower-cased word against the demo list, so
  `{"concept": "medication", "value": "oxybutynin 5 mg"}` and `{"concept": "oxybutynin", ...}` both
  match, and "paracetamol" does not. Only `ordered` and `administered` events count; `stopped` and
  `mentioned` never create a tag.
- **Fever.** `temperature_c` with a finite number of 37.8 or more and polarity `present`.
  Non-numeric values are ignored rather than rejected.
- **Quote span.** The tag copies the record's own quote and offsets from `extract()`. The same
  offsets index published `canonical_text`, and `fact_id` links the tag to the
  fact with the identical span.
- **Polarity.** Only `present` records make a tag, so "oxybutynin not given" or an uncertain
  mention never does.
- **Window.** `valid_from` is the record's `effective_from`, else `recorded_at`. Only `context.*`
  records may set `valid_to`; medication and fever tags always get the taxonomy window (7 days,
  48 hours) so an order with a long `effective_to` cannot hold a watch window open.
  `exertion` stays open-ended when no `valid_to` is given. `language_change` belongs to one
  check only; generic `POST /context` rejects it with 422, and structured source extraction skips
  it, until check-linked metadata support exists. A resident-wide interval cannot represent it.
- **`POST /context` timestamps.** `valid_from` is required and used as `recorded_at`, because the
  idempotency hash covers the whole source and a server-side `now()` would make every replay a 409.
- **Replay after purge.** `POST /context` with a key whose source was purged or retracted returns
  409 `source_purged` / `source_retracted` instead of re-inserting the tag.
- **Purge (migration 004).** `context_tags.quote` copies source text, so purging a source must
  delete its tags. BL-03 made `context_tags` append-only for `pm_runtime`; migration 004 keeps that
  except that a care-team member may delete a tag whose source is marked `purge_requested`.
  `purge_once` deletes by `source_id`. This narrows, but is still an exception to, the BL-03 rule.

## Not covered here

- Retracted sources keep their tags. Readers (verdict BL-11, overview BL-13) must join to
  `sources` and ignore tags whose source has `retracted_at` set.
- Gemini free-text extraction (`extracted_by = 'gemini'`) is a separate ticket.

## Review correction (17 Oct 2026)

The initial implementation exposed context tags before their facts/canonical source were published,
leaving citations unavailable until a worker ran. Synchronous publication now preserves evidence
atomicity and revision/cache invalidation. Regression contracts check immediate evidence resolution,
rollback of every database derivative, and replay without a second revision. Language-change
rejection prevents an open-ended explainer from suppressing future unrelated changes.
Synchronous completion clears any prior job lease; worker failure updates also require a processing
job, so an in-flight worker cannot requeue a source completed by a context replay.
