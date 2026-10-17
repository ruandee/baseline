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
treatment phrases, and the exact fixed `Suggest {action label}.` R sentence with no appended advice. Other than a B
sentence with no supplied context, sentences must cite evidence. Any provider/schema/validation
failure uses the deterministic template, preserving the check and original verdict. No provider
request/response or exception text is logged. Citation membership and numeric overlap alone cannot establish semantic support: a model could
otherwise append treatment advice or invent negative findings while reusing a permitted ID.
Therefore the server constructs allowed `(section, text, evidence_ids)` sentence options from
computed measurements, selected context and the fixed decision. The provider can only assemble
those exact supported options; paraphrases, added advice, unsupported negatives, swapped numeric
relationships and misattributed tag sentences are rejected to the template. This deliberately
narrows the original free-form drafting design to constrained assembly. These checks establish
consistency with supplied data, not clinical truth or completeness; the UI must still label the
output as a draft for verification.

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
failures, unsupported negative/positive claims, appended action advice, attribution and no-network
stub behavior. DB tests exercise saved drafts and scoped evidence reads
with mocked provider calls. Full CI, BL-10 client integration and the BL-11 lifecycle fix must
pass before BL-12 is complete. Live Gemini generation has not been run by this change.


## Post-commit drafting and concurrency

Deterministic scoring, shift-budget reservation and the safe template commit together under the
existing tenant-then-patient locks. The synchronous upload route then calls
`enrich_assessment_sbar` after that transaction closes. It takes a short authorized snapshot,
runs the bounded provider with no database connection or advisory lock held, then opens a short
patient-locked transaction to recheck care-team access, source revision, check usability and
unchanged assessment inputs before replacing only `sbar`. Publishing a draft does not consume
another budget slot or bump the source revision.

Provider/schema/grounding failure preserves the already committed check and template. A source
revision or assessment-eligibility change discards the generated prose and returns 409
`memory_changed`; revoked access returns 404. The original check remains stored, so these errors
must not be treated as evidence that upload storage rolled back. This prevents the response from
returning copied evidence that was withdrawn during model latency. Direct fixture callers may
store the deterministic assessment and explicitly invoke enrichment after committing.

Regressions check that an independent connection can acquire both tenant and patient locks and
read the committed template while the provider runs. Concurrent source retraction, purge, revision
change and assignment revocation discard the draft; check and budget audit records survive. No
provider I/O runs inside the budget critical section, avoiding a 15-second provider wait making
other uploads/watchlist requests hit the 10-second database statement timeout.
