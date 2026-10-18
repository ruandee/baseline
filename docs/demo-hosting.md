# BL-20 synthetic demo host

This is a deployment recipe, not evidence of a running deployment. Bootstrap seeds six empty
synthetic residents in tenant 0. The optional `load` step runs BL-14's merged loader
(`scripts/load_baseline_demo.py`, decision 008), which reuses the same tenant-0 nurse and patient
UUIDs (`uid("0/patient-N")`) and provisions the 12 fictional residents. No second hosting cohort
exists. The API reads the roster the seeded nurse can see (runtime role, RLS) at startup, so
recreate `api` after loading. BL-21 owns current-time reset; it is not integrated here.

Use a dedicated Linux VM with Docker Compose, a DNS hostname pointed at it, and inbound TCP
80/443 (UDP 443 optional). The spec suggests 4 vCPU/8 GB. Anyone with the URL receives the nurse
token (decision 005); keep it within the demo team. Only fictional data is supported.

From the repo root, copy `deploy/demo.env.example` to `.env.demo`, restrict permissions, set
`PM_DEMO_DOMAIN` and matching `PM_FRONTEND_HOSTS`, and generate a random `PM_JWT_SECRET` of at
least 32 characters. Keep `PM_PROVIDER=stub` for deterministic/no-cost operation. Never commit
the file or paste secrets into an issue, PR, or shared terminal transcript.

```sh
cp deploy/demo.env.example .env.demo
chmod 600 .env.demo
# Edit .env.demo; leave PM_DEMO_TOKEN blank for bootstrap only.
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml build
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml up -d --wait db object-store
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml run --rm migrate
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml run --rm bootstrap
# Optional: BL-14's 12 residents (offline, no provider calls; set PM_DEMO_PRESENTATION).
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml run --rm load
```

`load` is the only step besides `migrate`/`bootstrap` that receives the admin database URL. It
runs offline (keyword note extraction, template SBARs) and exits nonzero if any declared snapshot
mismatches. Its report and a loader-minted nurse token go to the `demo_artifacts` volume
(`/app/artifacts/baseline-demo`), never stdout; the hosted session still serves bootstrap's
`PM_DEMO_TOKEN`. `PM_DEMO_PRESENTATION` picks `all-history` (default) or `scenario-snapshots`;
both are retrospective event-time replays, not a current-date demo (decision 008). Loading after
the API is up needs `up -d --wait --force-recreate api` to refresh the roster.

Bootstrap prints a nurse token. Paste it into `PM_DEMO_TOKEN` in `.env.demo` before startup.
It expires after `PM_TOKEN_TTL_HOURS` (default 48, decision 009). Refresh by running bootstrap,
updating the file, and recreating API. Bootstrap provisions identities without deleting data.
A running API keeps serving the token it started with, so an expired token shows up as 401s
until API is recreated.

`serve` and `worker` refuse to start if `PM_ADMIN_DATABASE_URL` is non-empty (the overlay blanks
it); only `migrate` and `bootstrap` get the superuser URL. `serve` also refuses missing or
wildcard/port/scheme `PM_FRONTEND_HOSTS`, the local signing secret, and any `PM_DEMO_TOKEN` that
is not a valid, unexpired tenant-0 nurse token, and an empty roster (bootstrap not run). It
logs a warning at startup when the token expires within 24 hours.

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml up -d --wait api worker caddy
```

Open `https://YOUR_HOST/check`. API and assets share one origin. First startup downloads Whisper
`base` into the persistent `whisper` volume; allow outbound HTTPS for download and certificate
issuance. The API healthcheck is `python -m scripts.hosted_demo check`: runtime DB role, the
bootstrapped nurse principal, the bucket, ffmpeg and liveness. Whisper loads before uvicorn
accepts connections, so a passing check also means the model load was attempted; a failed load
is logged and retried on the first check. Caddy starts only after this passes. Wait for warmup
and send a synthetic clip before timing. The `/check` recorder (BL-17, #50) is merged; the
`/resident/{id}` page (BL-19, #55) is not yet. Never publish API port 8001: forwarded-header trust assumes Compose-only
access. Database and LocalStack retain loopback development ports and synthetic passwords.

Record acceptance in #22 before closing:

- Commit/image, host resources, UTC time and HTTPS hostname; keep bearer tokens private.
- Full documented CI suite against services; invalid token/Host/origin checks and an unassigned
  patient returning 404.
- Phone with Wi-Fi disabled: HTTPS microphone permission, ten-second synthetic counting clip,
  result including unusable/error states; actual Safari/mp4 and Chrome/webm verification.
- Warm upload-to-result latency: BL-07 target is p95 below five seconds.
- `/unit` against the loaded roster, and `/resident/{id}` once BL-19 (#55) lands.

Stop public access after demo:

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml stop caddy api worker kaze-worker
```

Preserve volumes until a deliberate synthetic reset. Revoke signing secret/unpublish DNS when
retiring. Do not use `down -v` if teammate clips or non-fixture data might exist. A laptop tunnel
is the fallback: keep backend loopback (`serve` binds 127.0.0.1 unless `PM_BIND_HOST` is
set), configure its exact public hostname/token and verify forwarded scheme/Host. The tunnel route has not been tested.

CI (`.github/workflows/demo-image.yml`, `deploy/ci-smoke.sh`) builds the image and runs this
sequence against `localhost` with Caddy's internal CA and Whisper `tiny`: guard refusals with
their messages (admin URL, wildcard host, missing token, default signing secret), readiness,
unpublished API port, same-origin page/assets/session, Host/Origin/bearer/unassigned-patient
rejections, a tone upload through Caddy that must report ASR timing (decode/VAD/Whisper/storage
plumbing, not speech validation), the six-resident bootstrap roster, the loader followed by an
API recreate showing 12 residents, and a running worker. It does not prove public DNS, ACME certificates, phone
browsers, LTE or latency.

References: [Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/),
[Caddy proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers).

The image smoke loads the cohort before its first uploaded check. Loader preflight rejects
previously recorded seed patients deliberately; it never overwrites an upload to make setup pass.
The API is recreated and its twelve-patient session roster refreshed before upload plumbing runs.

During first setup, run the cohort load before starting the long-running worker. The loader
publishes its own queued sources before scoring; a concurrent worker can hold a source lease
and correctly make the strict loader report incomplete. The image smoke follows the same order.

For a guided VM/DNS path and private nurse/PSW bootstrap without printing tokens, see
[the deployment path](deployment-path.md). Use `deploy/start-demo.sh first` for a pristine setup
and `refresh` for token refresh without reloading/deleting checks.
