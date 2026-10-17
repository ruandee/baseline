# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/decisions/`**: this repo's ADR directory (not `docs/adr/`). Read the decision records that touch the area you're about to work in. Files are numbered `NNN-short-name.md`.

If either doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved. New ADRs go in `docs/decisions/` with the next free number; check the directory first, because the number is easy to collide on when several people add records at once.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── docs/decisions/
│   ├── 001-synthetic-runtime.md
│   └── 002-model-adapters.md
└── src/patient_memory/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Repo invariants take precedence

`AGENTS.md` carries the authorization and temporal invariants (tenant/patient scope, `as_of` vs `known_at`, immutable sources, synthetic data only). Treat them as hard constraints, not preferences.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR 003 (change notifications), but worth reopening because…_
