# 034: Public overview and documentation navigation

## Decision

Present the repository as Baseline, with a reader-facing explanation, reproducible local setup,
concise stack summary and explicit prototype limits. Replace the README's duplicated ticket
status with a link to `docs/build-status.md`.

Add a documentation index and stack study guide. Move hackathon submission drafts and rehearsal
logistics from `docs/submission/` to `docs/internal/submission/`, preserving their contents.
Internal notes remain publicly readable if the repository is public; the directory is not an
access control. Retain specifications, build status, agent workflows and decisions because they
explain contracts and guide safe contributions. Leave existing untracked personal files alone.

## Rationale and contracts

Readers need a coherent introduction rather than stale merge queues and editor instructions.
A single runtime-status reference reduces conflicting completion claims. Historical submission
material remains available without appearing among the primary reader guides.

No API, data, authorization or runtime contracts change. Documentation paths for submission
material change; relative links in moved files are adjusted to their new location.
