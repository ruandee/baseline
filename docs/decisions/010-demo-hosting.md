# 010: Opt-in container demo behind Caddy

Status: proposed (BL-20, issue #22; HTTPS/LTE acceptance pending).

Keep local Compose unchanged. An explicit `compose.demo.yaml` overlay adds an ffmpeg-equipped
Python image, tenant-0 ingestion worker, same-origin API/frontend and Caddy TLS proxy. There is
no `web/` service (decision 005). Caddy is the only publicly published service; database and
object-store ports remain bound to host loopback. Compose waits for healthy storage services;
migrations and identity bootstrap are explicit one-off CLI operations.

Hosted startup (both `scripts.hosted_demo serve` and `scripts.frontend` with `PM_FRONTEND_HOSTS`)
rejects the local signing secret, missing hosts/token, expired token and any
token other than the seeded tenant-0 nurse. Bootstrap prints only that nurse token; it does not
reset data. Normal API/worker processes receive no admin database URL and refuse to start with
one. The six-patient seed is an empty roster, not BL-14's story cohort. The hosted session lists
the patients the seeded nurse can read through the runtime role (RLS) at API startup, so BL-14's
loader (PR #53, same tenant-0 nurse/patient UUIDs) supplies the 12-resident mapping without a
second hosting cohort. BL-21 must integrate its reset here and recreate API afterwards.

The container API trusts forwarded headers from private Compose peers because its port is not
published. Caddy supplies the public Host and HTTPS scheme; existing host/origin/session checks
remain. This trust requires a dedicated host with controlled Docker access. Standalone startup
defaults to trusting localhost. Never expose API port 8001 with wildcard proxy trust. No
workspace bind mount or secrets enter the image build.

Tokens use `PM_TOKEN_TTL_HOURS` (default 48 since BL-01). Refresh via bootstrap, update
`.env.demo`, recreate API before expiry. The API healthcheck is a readiness probe (runtime DB
role, bootstrapped nurse, bucket, ffmpeg, liveness) so Caddy never fronts an unbootstrapped API.
A CI job builds the image and smoke-tests the stack on localhost (completion branch
`bl/bl-20-host-completion`). No public hosting or real voice collection was
performed. API/evidence contracts are unchanged.

Remaining gate: CI image smoke green, HTTPS domain, model warmup, phone LTE result,
latency measurement and teardown. Issue #22 stays open until acceptance succeeds.
