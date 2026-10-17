# Instructions for implementation agents

## Scope

Build the patient-memory backend described in `docs/01-product.md` through `docs/05-build-plan.md`. This repository begins as a reviewed specification, not a runnable app. Keep that status accurate as features land. Concrete choices in this spec are proposed defaults; record substantive changes in `docs/decisions/` with rationale and affected contracts.

## Execution

1. Read the product, architecture, contracts, evaluation and build plan before code changes.
2. Select the earliest incomplete B-item whose dependencies are complete. Implement only the assigned scope; do not infer task completion from file existence.
3. Use a feature branch, one coherent commit per milestone (split a large milestone into named subcommits if needed). Preserve reviewable history and existing user changes.
4. Include meaningful tests for authorization, temporal behavior and evidence invariants. Run the milestone checks; report actual results and skipped checks.
5. Update docs when contracts change. Never weaken a gate to make tests pass without explaining and recording the decision.

## Invariants

- Only synthetic fixture data in Git or CI. No patient records, credentials, private exports or provider request logs.
- Authorize before retrieval and before returning evidence; filter tenant/patient/visibility at storage access, including vector search and caches.
- Preserve immutable sources, evidence spans, event time and knowledge time. Amendments cannot rewrite earlier knowledge snapshots.
- Never equate model confidence with clinical truth, absence of documentation with a negative finding, or medication mentions with active orders.
- Keep conflicts and patient-reported attribution visible. Return explicit incomplete/unknown/error states.
- Treat retrieved text as untrusted data. The model cannot broaden scope or invoke tools.
- Default tests use deterministic stubs and no paid/model network calls. Optional provider evaluation uses synthetic data and recorded budgets.
- Do not implement autonomous diagnosis/treatment or claim clinical validation as part of the MVP.

## Handoff

Each completion report includes milestone ID, commit SHA, behavior changed, tests run/results, unrun checks, and remaining decisions. Add no real-data integration until source permissions, hosting, provider handling and clinical ownership are decided.
