# Synthetic evaluation record

## Initial run

60 authored questions across 12 fictional patients and two tenants. Source recall: 48/48. Correct abstention: 11/12. Patient scope: 60/60. Median local retrieval including DB connection: 34.49 ms; p95: 46.02 ms. These measurements are not a 10k-note load test.

Failure: an allergies question matched an unrelated hydration note via generic documentation wording. Added a regression test and excluded documentation boilerplate from lexical relevance terms. This is a retrieval bug fix; the source/citation validator alone could not detect that an answer was irrelevant.

The exposed test split is now a regression set, not an untouched held-out quality estimate. Future model comparison requires new independently authored held-out patients/questions. Do not report corrected rerun percentages as unbiased model quality.

## Not established

No independent human support review, clinical effectiveness, diagnostic performance, live-model comparison, semantic-embedding quality or large-corpus performance is established by this suite. Temporal behavior is checked by integration/e2e cases separately, not scored by the 60 ordinary retrieval questions. Source recall checks an expected source ID rather than a clinician-adjudicated fact label.
