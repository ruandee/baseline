# Agent implementation and review plan

## Working agreement

This repository initially contains specifications only. Each B-item below is a future implementation commit, not an existing feature. Execute in dependency order on feature branches, keeping migrations with the feature they enable. Do not squash independently reviewable milestones. A reviewer should be able to inspect each commit's behavior and evidence without reading agent chat history.

| ID / proposed commit | Depends on | Work and ownership boundary | Done when / review evidence |
| --- | --- | --- | --- |
| B01 `chore: bootstrap backend and reproducible local tooling` | — | Runtime package, locked deps, Compose db/object store, stub config, CI lint/unit checks | Clean clone starts; no model key required; README contains exact commands; lockfile checked |
| B02 `feat: define API contracts and authorization boundary` | B01 | Pydantic contracts, generated OpenAPI, identity adapter, assignment/role checks, error envelope | Role-route matrix tests; production rejects dev auth; invalid intervals and schemas rejected |
| B03 `feat: add temporal storage and synthetic fixtures` | B02 | Migrations for entities, composite constraints, RLS, fixture loader | E02/E05/E06 storage cases; upgrade from empty DB; runtime-role RLS test; 12 patients/two tenants |
| B04 `feat: ingest immutable source versions with resumable jobs` | B03 | Source API, object staging, idempotency, leases, retry, publication/revision transaction | E12 and partial-ingestion failures; restart demo; no duplicate versions |
| B05 `feat: extract evidence-linked facts and temporal relationships` | B04 | Normalization, chunk offsets, extraction interface/stub, fact validation, supersession/conflicts | E06–E10/E16/E17; exact source-span assertions; quarantined invalid extraction |
| B06 `feat: retrieve scoped temporal patient evidence` | B05 | SQL/lexical/vector adapters, fusion, bounded expansion, scope filters, timeline | E02–E07/E18; recall report and query plan; no global retrieval before filtering |
| B07 `feat: generate validated questions and shift summaries` | B06 | Generator adapter/stub, claim schema, evidence validator, unknown/conflict sections | E01/E03/E11/E13/E15; API example and end-to-end synthetic handover |
| B08 `feat: enforce cache invalidation audit and source lifecycle` | B07 | Cache keys/rechecks, revocation races, retraction/purge, audit redaction, operational metrics | E14/E19/E20; stale-answer concurrency test; cache/derivative invalidation evidence |
| B09 `test: add reproducible retrieval and grounding evaluations` | B08 | Frozen 60-question benchmark, metric definitions/report, contract/e2e CI gates | All deterministic gates pass; honest denominators and failure report; reproducible rerun |
| B10 `feat: add configurable model adapters and benchmark report` | B09 | Provider chosen by permitted-use review, timeouts/budgets, two-model comparison if credentials available | Offline tests still pass; synthetic model report or explicit unrun status; no claim of validated provider without evidence |
| B11 `docs: deliver backend demo and pilot readiness handoff` | B09; B10 if model demo desired | CLI demo, operations/restore guide, architecture updates, limitations | Reviewer reproduces import → summary → correction → changed answer → historical answer |

Use the module paths in the architecture as ownership boundaries. If multiple agents work later, assign disjoint branches/modules and merge through the dependency sequence; they must agree on B02/B03 contracts first. This plan does not require parallel agents.

## Task prompt template

> Implement Bxx only. Read AGENTS.md and the linked specifications. State assumptions, satisfy its acceptance cases, update relevant contracts/docs, and run the checks available for this milestone. Commit only this task's files with the listed commit subject. Report commit SHA, changed behavior, checks/results and remaining limitations. Do not mark later milestones complete or silently relax a gate.

## Review checklist for every implementation commit

- What observable behavior changed, and which R/E IDs does it address?
- Are migrations, access scope and temporal filters consistent with the contracts?
- Do evidence spans resolve exactly, including Unicode and amended sources?
- Are failure/incomplete states distinguishable from empty evidence?
- What commands actually ran and passed? Name skipped checks and why.
- Are dependencies pinned, fixtures synthetic and logs free of note text/secrets?
- Can the change be reverted without losing source data? Provide migration rollback/forward-repair notes; do not automatically downgrade a live database.

## Review checkpoints

After B03: review identity and time semantics before adding retrieval. After B07: review the first end-to-end behavior. After B09: inspect benchmark failures before choosing a model. After B11: decide separately whether to pursue a real-data pilot or a diagnosis research study.

## Deferred diagnosis research

If pursued, define a separate protocol and task label, evaluation horizon, allowed evidence, independent held-out patients, leakage exclusions, clinician-reviewed reference labels, calibration and subgroup analysis. Compare the same model with and without retrieved memory. A good handover summary is not evidence of diagnostic improvement. Do not place experimental diagnostic outputs in the nurse-facing MVP response schema.
