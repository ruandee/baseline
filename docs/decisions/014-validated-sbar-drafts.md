# 014: Validate SBAR drafts and keep a deterministic fallback

Status: proposed implementation; BL-12 acceptance awaits integration and CI, 2026-10-17.

The change engine and verdict rules decide the result before drafting. For watch/escalate,
`baseline.sbar` sends only the display name, computed feature values rounded to display
precision, selected valid context labels/quotes/IDs, status, verdict and fixed action label
to the shared bounded `baseline.llm.request_json` client. Stub mode never calls a provider.
Explained, enrolling and within-normal results do not request or store an SBAR.

The strict output schema bounds sentence counts/lengths and rejects extra fields. Validation
requires all S/B/A/R sections, exact evidence IDs from the supplied check/tag bundle, numeric
tokens from the rounded supplied measurements or fixed action label, no banned diagnostic or
treatment phrases, and the exact suggested action label in every R sentence. Other than a B
sentence with no supplied context, sentences must cite evidence. Any provider/schema/validation
failure uses the deterministic template, preserving the check and original verdict. No provider
request/response or exception text is logged. These checks do not establish that arbitrary prose
is semantically true; the UI must continue to label generated prose as a draft for verification.

## Citation contract

The model sees the raw check UUID and context-tag UUIDs specified in docs/06. Only after
validation are those mapped to the existing resident UI citation convention: `check:<uuid>`
for signal data, fact UUID for a context source. A tag without a resolvable fact is omitted
from the provider bundle. The stored `source` is `gemini` or `template` (the former denotes
the configured model path, including compatible/native adapters). No API or schema migration
is introduced. The existing `verdict.sbar_template` import delegates to the new module.

The template says context was not supplied rather than implying a documented negative finding.
Source-revision invalidation, retraction/purge cleanup and read-time provenance checks remain
mandatory in BL-11 integration; generating from currently valid context alone cannot invalidate
already stored prose. No prompt, quote copy or provider result is cached by this module.

## Acceptance

Deterministic unit tests exercise all five validators, rounding, citation mapping, provider
failures and no-network stub behavior. DB tests exercise saved drafts and scoped evidence reads
with mocked provider calls. Full CI, BL-10 client integration and the BL-11 lifecycle fix must
pass before BL-12 is complete. Live Gemini generation has not been run by this change.
