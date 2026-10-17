# Implementation review handoff

Implemented on `build/backend-mvp` with separate commits. Read this alongside the original target specification; implementation does not imply all research/pilot gates are met.

| Milestone | Implemented behavior | Remaining scope or gate |
| --- | --- | --- |
| B01 | Locked Python project, Compose, CI checks | Windows local and CI Linux validation recorded separately |
| B02 | Pydantic contracts, bearer JWT validation, membership/assignment checks, error envelope, generated OpenAPI | Production identity is deliberately disabled |
| B03 | Composite constraints, forced RLS, non-owner runtime, two-tenant fixtures | Actual clinical identity/source mapping deferred |
| B04 | Immutable S3 objects, idempotency, leased jobs, retry/backoff, atomic publication | Production queue/load operations not validated |
| B05 | Exact Unicode spans, structured facts, intervals, relationships, conservative note assertions | No validated clinical free-text extractor or semantic conflict resolution |
| B06 | Patient/time-scoped full-text/hash-vector fusion, timeline, conflict/order evidence expansion | Real semantic embeddings and model-specific tokenizer budget remain future work |
| B07 | Questions/summaries, exact citations, unknowns/conflicts, provider/schema failures | Summary is an evidence selection, not free-form clinical prose |
| B08 | Permission/revision rechecks, scoped cache, shared rate limits, audit, retraction/visibility/purge | Pilot retention/backup expiry policy remains undecided |
| B09 | E01Ã¢â‚¬â€œE20 engineering cases and 60-question synthetic regression runner | Clinical/human support gates and untouched model test set remain unmet |
| B10 | Optional compatible HTTP adapter and native Ollama structured selection | Live local Qwen3.5 trial documented in local-model-results.md; two-model quality comparison remains unrun |
| B11 | Runnable HTTP demo, longitudinal loader, repair/reconciliation tools, operations guide | Real-data pilot and hospital integration require separate decisions |

The latest full local suite at this point passed 42 tests, including actual PostgreSQL/S3 integration; lint passed. The 60-question offline regression returned expected-source recall 48/48, correct abstention 12/12 and in-scope retrieval 60/60. Human support review is explicitly unmeasured. The first benchmark exposed a false relevance match; its failure is preserved in `docs/evaluation-results.md`.

To reproduce, follow README from a clean clone, then run the tests/evaluation and demo. Optional live-model calls are not run by ordinary tests or CI. Review the changed behavior and limits before approving a pilot; no deployment has been performed.


## B12: Synthetic frontend walkthrough

Backend PR #1 was merged before this frontend milestone. The same-origin `/app/` interface now provides a six-patient directory, shift summaries, questions, source timeline and citation inspection. It connects to the existing authenticated endpoints and deterministic stub provider. The local launcher creates a nurse-scoped synthetic session; demo tokens stay in tab-scoped session storage after the URL fragment is removed; refresh preserves the session and Disconnect clears it.

Validation: the existing 42-test suite passed, and both new frontend contract tests passed (44 total). The new tests cover the public shell, required API authentication, nurse access, cross-patient isolation and denied imports. Ruff and JavaScript syntax checks passed. Headless Chrome verified live summaries, six patients, citation retrieval, unsupported-question abstention, timeline, patient switching, disconnect/reconnect, a simulated service failure, and mobile layout without horizontal overflow or uncaught browser errors. Desktop and mobile screenshots were inspected.

Remaining: Codex SDK integration, clinical quality evaluation, production identity and real-data handling are not implemented by this milestone. This is a synthetic evidence-selection walkthrough, not a validated prediction system. Live paid-provider checks were not run.

B12 refresh fix: Chrome verified that a page reload restores the connected demo, and that Disconnect followed by reload leaves the workspace disconnected. JavaScript syntax and diff checks passed. Backend behavior is unchanged; the backend suite was not rerun for this browser-only fix.
