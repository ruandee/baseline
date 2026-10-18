# BL-20 synthetic demo host

This recipe describes the integrated checkout; the dated snapshot below records one deployed
release and its narrower verification. Bootstrap seeds six empty
synthetic residents in tenant 0. The optional `load` step runs BL-14's merged loader
(`scripts/load_baseline_demo.py`, decision 008), which reuses the same tenant-0 nurse and patient
UUIDs (`uid("0/patient-N")`) and provisions the 12 fictional residents. No second hosting cohort
exists. The API reads the roster the seeded nurse can see (runtime role, RLS) at startup, so
recreate `api` after loading. For BL-21's merged current-time reset, see the
[deployment path](deployment-path.md#one-command-current-day-core-demo-reset-bl-21).

Use a dedicated Linux VM with Docker Compose, a DNS hostname pointed at it, and inbound TCP
80/443 (UDP 443 optional). The spec suggests 4 vCPU/8 GB. Anyone with the URL receives the nurse
token (decision 005); keep it within the demo team. Only fictional data is supported.

For a fresh host, run these commands from the reviewed checkout. Replace the hostname with
yours. The initializer creates a private `.env.demo`, matching Host allowlist and random signing
secret; it refuses to overwrite existing configuration. Keep `PM_PROVIDER=stub` for
deterministic/no-model-call operation. Never commit the file or paste secrets into an issue,
PR, or shared terminal transcript. Do not enable shell tracing.

```sh
bash deploy/check-host.sh
python3 -m scripts.prepare_deployment init baseline.example.org
# Optionally choose PM_DEMO_PRESENTATION in the private file before the first load.
bash deploy/start-demo.sh first
# Later: refresh credentials without reloading or deleting checks.
bash deploy/start-demo.sh refresh
```

Use either your documented non-root Docker setup or `sudo` for the host/start helpers if Docker
requires it. Keep the private file's permissions restricted; do not make it world-readable.
`first` builds the image, migrates, bootstraps separate nurse/PSW identities, loads the cohort
before the resident worker starts, and starts the services. On current main it also bootstraps
the separate KAZE identity and starts `kaze-worker`, without granting consent or sending SMS.
Do not run `first` on an existing deployment; use `refresh` or the documented fixture reset.

The one-off `migrate`, `bootstrap`, `load` and `kaze-bootstrap` services receive the admin
database URL; long-running services do not. `load` runs offline (keyword note extraction,
template SBARs) and exits nonzero if any declared snapshot
mismatches. Its report and a loader-minted nurse token go to the `demo_artifacts` volume
(`/app/artifacts/baseline-demo`), never stdout; the hosted session still serves bootstrap's
`PM_DEMO_TOKEN`. `PM_DEMO_PRESENTATION` picks `all-history` (default) or `scenario-snapshots`;
both are retrospective event-time replays, not a current-date demo (decision 008). Loading after
the API is up needs `up -d --wait --force-recreate api` to refresh the roster.

The helper captures bootstrap credentials privately and writes distinct `PM_DEMO_TOKEN` and
`PM_DEMO_PSW_TOKEN` values without printing them. Tokens expire after `PM_TOKEN_TTL_HOURS`
(default 48, decision 009). `refresh` updates credentials and recreates the serving services,
preserving the signing secret and existing checks. A running API keeps serving its startup
token, so editing the private file alone does not refresh an expired browser session.

`serve`, `worker` and `kaze-worker` refuse to start if `PM_ADMIN_DATABASE_URL` is non-empty
(the overlay blanks it). `serve` also refuses missing or
wildcard/port/scheme `PM_FRONTEND_HOSTS`, the local signing secret, and any `PM_DEMO_TOKEN` that
is not a valid, unexpired tenant-0 nurse token, and an empty roster (bootstrap not run). It
logs a warning at startup when the token expires within 24 hours. Nurse and PSW credentials
must match their separate seeded identities; substituting the nurse token for PSW is rejected.

Open `https://YOUR_HOST/check`. API and assets share one origin. First startup downloads Whisper
`base` into the persistent `whisper` volume; allow outbound HTTPS for download and certificate
issuance. The API healthcheck is `python -m scripts.hosted_demo check`: runtime DB role, the
bootstrapped nurse principal, the bucket, ffmpeg and liveness. Whisper loads before uvicorn
accepts connections, so a passing check also means the model load was attempted; a failed load
is logged and retried on the first check. Caddy starts only after this passes. Wait for warmup
and, once recording is authorized, send a synthetic clip before timing. The `/check` recorder
(BL-17, #50) and `/resident/{id}` page (BL-19, #55) are merged. Never publish API port 8001:
forwarded-header trust assumes Compose-only
access. Database and LocalStack retain loopback development ports and synthetic passwords.

Record acceptance in #22 before closing:

- Commit/image, host resources, UTC time and HTTPS hostname; keep bearer tokens private.
- Full documented CI suite against services; invalid token/Host/origin checks and an unassigned
  patient returning 404.
- Phone with Wi-Fi disabled: HTTPS microphone permission, ten-second synthetic counting clip,
  result including unusable/error states; actual Safari/mp4 and Chrome/webm verification.
- Warm upload-to-result latency: BL-07 target is p95 below five seconds.
- `/unit` against the loaded roster, plus `/resident/{id}` and its evidence readback.

## Verified deployment snapshot: 2026-10-18 UTC

This is a frozen record of the deployment performed in the operator session, distinct from
features available on a later main branch. Host: `baseline.deeruan.com`, Google Cloud project
`baseline-deeruan-demo`, VM `baseline-demo`, zone `us-central1-a`. The VM runs Ubuntu 24.04
amd64 with 4 vCPUs, 16 GB RAM and a 50 GB disk. The deployed commit is
`6e4d7d95f288abd860b124f121b8d28468cfa9ff`, using `PM_PROVIDER=stub`,
`PM_DEMO_PRESENTATION=scenario-snapshots` and `PM_KEEP_AUDIO=false`.

Verified through terminal/SSH after the first setup:

- Public HTTPS GET `/unit` returned 200 with certificate verification enabled. Google Public
  DNS resolved the hostname to the VM. `/check`, `/check?mode=live`, the JavaScript asset,
  liveness and a resident page/overview also returned 200.
- Nurse session and watchlist contained 12 residents: Mrs. K escalated, Mrs. L was on watch,
  Mr. T was explained, and nine were within normal. These are historical scenario snapshots.
- Separate PSW credentials returned a 12-person due roster without risk fields; PSW watchlist
  access and an unassigned patient returned 404. Invalid bearer returned 401; missing demo
  header, foreign/insecure Origin and foreign Host checks returned 403.
- API, Caddy, database, object store and resident worker started successfully. The API had no
  admin database URL, FFmpeg was installed, and public TCP 8001, 55432 and 59000 were unreachable.
- Restarting the API preserved all 12 residents and the expected scenario verdicts.

This deployed revision predates the hosted KAZE worker and current-day reset integration.
Do not infer that newer main features have been rolled out. No recordings, paid model calls,
real SMS, physical-phone/LTE checks, citation-click UI acceptance or latency measurements were
performed in this deployment session. Issue #22 remains open for its remaining gates.

The VM was configured to stop after 24 hours, approximately **2026-10-19 01:09 UTC**
(October 18, 9:09 PM Toronto time). That stops compute; retained disk/static-IP resources
still need a deliberate retirement decision. Recheck the actual VM schedule if it is restarted.

## Shutdown

Stop public access after demo, using the Compose file from the deployed checkout:

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml stop caddy api worker kaze-worker
```

On the pinned `6e4d7d9` deployment above, omit `kaze-worker`: that revision has no such service.

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
