# 035: Permit external navigation to the hosted demo shell

Status: implemented for synthetic hosted demos, 2026-10-18.

The workspace guard rejected every cross-site request except a valid acknowledgement
navigation. This also rejected a judge following a link from a submission or chat to `/unit`.
The shell is already a public, static HTML document in explicitly configured hosted mode;
it contains neither patient records nor a bearer token.

Permit GET document navigations to the exact public shell routes (`/`, `/unit`, `/check`,
`/resident/{id}`, `/out`, `/out/session/{id}`) when hosted mode is explicitly enabled.
The destination must be `document` and fetch mode `navigate`. An external Origin is permitted
for that navigation only. The configured Host allowlist, deployment secret, no-store response
and frame-ancestor CSP remain required.

This exception does not cover `/demo/session`, API routes, assets, POSTs, frames or ordinary
cross-site fetches. Those retain their Origin/fetch-site checks. Bootstrap still requires its
explicit header, uses separate scoped identities and returns only the configured synthetic
session; clinical routes still authorize before reading. Local mode continues to reject
off-loopback clients. The existing narrowly scoped acknowledgement exception is unchanged.

Tests cover all shell routes, missing navigation semantics, foreign Host, API/assets, POST and
local-mode isolation. This does not make the demo appropriate for real patient data or add
production authentication. It fixes navigation to the intentionally public synthetic shell.
