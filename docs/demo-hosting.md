# BL-20 synthetic demo host

This is a deployment recipe, not evidence of a running deployment. BL-14/21 supply the full cohort
and reset. Current seed gives six empty synthetic residents in tenant 0.

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
```

Bootstrap prints a nurse token. Paste it into `PM_DEMO_TOKEN` in `.env.demo` before startup.
It currently expires in eight hours; BL-01 extends this to 48. Refresh by running bootstrap,
updating the file, and recreating API. Bootstrap provisions identities without deleting data.

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml up -d --wait api worker caddy
```

Open `https://YOUR_HOST/check`. API and assets share one origin. First startup downloads Whisper
`base` into the persistent `whisper` volume; allow outbound HTTPS for download and certificate
issuance. Wait for warmup and send a synthetic clip before timing. Liveness does not prove model
or database readiness. Never publish API port 8001: forwarded-header trust assumes Compose-only
access. Database and LocalStack retain loopback development ports and synthetic passwords.

Record acceptance in #22 before closing:

- Commit/image, host resources, UTC time and HTTPS hostname; keep bearer tokens private.
- Full documented CI suite against services; invalid token/Host/origin checks and an unassigned
  patient returning 404.
- Phone with Wi-Fi disabled: HTTPS microphone permission, ten-second synthetic counting clip,
  result including unusable/error states; actual Safari/mp4 and Chrome/webm verification.
- Warm upload-to-result latency: BL-07 target is p95 below five seconds.
- `/unit` and `/resident/{id}` when their tickets land; main currently has only scaffold pages.

Stop public access after demo:

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml stop caddy api worker
```

Preserve volumes until a deliberate synthetic reset. Revoke signing secret/unpublish DNS when
retiring. Do not use `down -v` if teammate clips or non-fixture data might exist. A laptop tunnel
is the fallback: keep backend loopback, configure its exact public hostname/token and verify
forwarded scheme/Host. The tunnel route has not been tested.

References: [Compose startup ordering](https://docs.docker.com/compose/how-tos/startup-order/),
[Caddy proxy headers](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers).
