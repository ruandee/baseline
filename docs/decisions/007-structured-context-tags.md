# 007: Structured context tags are derived in the worker and removed on purge

Status: accepted (17 Oct 2026, BL-09, issue #11).

## In plain words

The structured rules (high-risk medication, fever, `context.*` observations) run inside the
worker's publish transaction, next to fact extraction, so a tag and the facts it quotes appear
together or not at all. `POST /v1/patients/{id}/context` submits an `observation` source through
normal ingestion and writes the same tag immediately, so the 201 response already carries it.

Both paths build the tag from the same pure rules (`baseline/context.py`) and give it an id derived
from the source span and tag name, so the worker running later on a `POST /context` source inserts
nothing new, and a worker retry cannot duplicate a tag.

## Choices worth knowing

- **Where the drug name is matched.** The spec does not say whether the drug sits in `concept` or
  `value`. The rule checks both, as a whole lower-cased word against the demo list, so
  `{"concept": "medication", "value": "oxybutynin 5 mg"}` and `{"concept": "oxybutynin", ...}` both
  match, and "paracetamol" does not. Only `ordered` and `administered` events count; `stopped` and
  `mentioned` never create a tag.
- **Fever.** `temperature_c` with a finite number of 37.8 or more and polarity `present`.
  Non-numeric values are ignored rather than rejected.
- **Quote span.** The tag copies the record's own quote and offsets from `extract()`. The same
  offsets index `canonical_text` once the worker publishes it, and `fact_id` links the tag to the
  fact with the identical span.
- **Polarity.** Only `present` records make a tag, so "oxybutynin not given" or an uncertain
  mention never does.
- **Window.** `valid_from` is the record's `effective_from`, else `recorded_at`. Only `context.*`
  records may set `valid_to`; medication and fever tags always get the taxonomy window (7 days,
  48 hours) so an order with a long `effective_to` cannot hold a watch window open.
  `exertion` and `language_change` have no default and stay open-ended when no `valid_to` is given.
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
