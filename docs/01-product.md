# Product scope and source

## Source and interpretation

Source: [shared conversation](https://chatgpt.com/share/6ad2e965-a8b8-83ea-ba3e-1afcd5470baf), reviewed 2026-10-16 (America/Toronto). The browser exposed seven user messages but blank assistant responses. This specification derives requirements from those visible user messages; it does not reconstruct missing recommendations. The page title, “Obsidian Open Source Status,” is not the product name.

| ID | Requirement supported by the user's messages | Implementation interpretation |
| --- | --- | --- |
| R01 | Both nursing handover and a patient diary matter | Start with nurse read/query workflow; preserve patient-reported sources distinctly for later diary UI |
| R02 | AI should know a specific patient's history and answer nurse questions | Patient-scoped retrieval with source citations |
| R03 | Distinguish true, outdated and unknown information | Track provenance, effective times, corrections, conflicts and missing evidence; never label extraction as verified truth |
| R04 | Choose a model and content management approach; consider connected graphs | Benchmark interchangeable models; use relational memory first and explicit evidence links |
| R05 | Reduce hallucination | Ground answers, validate citations, abstain and evaluate unsupported claims |
| R06 | Plan the backend and retrieval system | API, ingestion, storage, indexing, retrieval, generation, audit and evaluation are in scope |
| R07 | Combine nursing notes and records into summaries and queries; potentially improve diagnosis prediction | Synthetic multi-source prototype first; diagnostic prediction is a separate future research track |

All concrete stack choices, thresholds, endpoint shapes and milestones below are proposed engineering defaults, not decisions recovered from the conversation.

## First usable vertical slice

A developer imports synthetic longitudinal notes and structured records for two patients. An authorized nurse can request a handover summary and ask what changed since the last shift. Every patient-specific assertion references an exact source span. An amended note changes subsequent answers while earlier knowledge snapshots remain reproducible. Missing, conflicting and old observations are visible. A different patient's information never enters the retrieval context.

## MVP features

- Nursing-note text/JSON import and normalized JSON observations, medication events and patient reports.
- Asynchronous, idempotent ingestion, explicit failure/retry state and a patient memory revision.
- A timeline, patient-scoped questions, and structured shift summaries with evidence.
- Historical queries with separate event-time and knowledge-time cutoffs.
- Explicit unknowns, unresolved conflicts, incomplete indexing and stale cached answers.
- Tenant membership, patient assignment checks, source visibility and audit events.
- A small CLI/demo client sufficient to exercise the backend; no full production UI.

## Boundaries

Do not implement prescribing, autonomous diagnosis, alerts that drive care, EHR writeback, patient identity matching, unrestricted agent tools, or autonomous care actions in the MVP. Do not infer a negative finding from absence of documentation. “No evidence found” and “documented negative” are different results. Medication mentions are not current medication orders. A patient report is not silently promoted to clinician-confirmed information.

Patient-controlled sharing, a production diary UI, FHIR adapters, hospital integration, graph databases, and real clinical evaluation follow the first prototype. Keep interfaces compatible with those additions without building them now.

## Success

The backend can demonstrate correct retrieval, evidence display, temporal correction and isolation on the evaluation cases. It must also demonstrate refusal to manufacture an answer when evidence is absent. The prototype is successful without proving improved diagnosis or clinical outcomes.
