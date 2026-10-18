# Live demo deployment path

This guide prepares the existing synthetic demo for a Linux VM. It does not provision billable
resources, change DNS, publish the repository or establish that a deployment has passed acceptance.
The integrated release must first pass backend and image CI. The current hosting recipe is
[demo-hosting.md](demo-hosting.md); use its commands from the repository root.

## What is deployed

The frontend is plain HTML, CSS and JavaScript under `frontend/`, served by FastAPI alongside
its API. Caddy terminates HTTPS. Docker Compose runs PostgreSQL/Timescale/pgvector, LocalStack
for synthetic object storage, the FastAPI/Whisper/FFmpeg image and a persistent worker. There is
no separate React/Next.js build or Vercel project to create. Real records are out of scope.

## Information needed at the deployment step

- Cloud provider and project/account, and an authorized way to access the VM. Do not put cloud
  keys, SSH private keys or passwords in chat, Git, issue bodies or shell transcripts.
- A DNS hostname controlled by the team, for example `baseline.example.org`, and the VM's public IP.
- Confirmation of available compute credits/budget and their expiry before creating a VM.
- Later: consenting phone testers/recordings, and verified demo contacts/provider configuration
  for real SMS. The default provider and sender remain offline/no-cost until configured.

Existing Google Cloud credits may be usable for Compute Engine, subject to their terms. Start
with a Linux VM around 4 vCPUs and 8?16 GiB RAM; this is an initial engineering size, not measured
latency acceptance. Do not use a micro/free-tier VM for the Whisper demo. No GPU is required by
the implementation. Provision disk space for the image, model cache and synthetic volumes.

## Cloud console and DNS sequence

1. In the chosen cloud project, create an Ubuntu Linux VM and enable SSH access through the
   provider's supported access mechanism. Record its resources and release commit.
2. Install Docker Engine and its Compose plugin using the official Ubuntu installation guide.
3. Permit public TCP 80 and 443 (UDP 443 optional). Keep database, object-store and API ports
   private; use the repository's loopback bindings and do not add public port mappings.
4. Point the chosen hostname's DNS A record at the VM's public IPv4. Add AAAA only if IPv6 is
   actually configured. Wait for public DNS resolution before expecting certificate issuance.
5. Clone this repository using authorized access. Select the reviewed release SHA, not a moving
   collection of unmerged branches. Use a dedicated working directory for the demo.

## Prepare private configuration

Run `bash deploy/check-host.sh` on the VM. Then create a fresh environment file:

```sh
python3 -m scripts.prepare_deployment init baseline.example.org
```

The helper refuses to replace an existing `.env.demo`, generates a deployment-only signing
secret and restricts the file to owner access on Linux. It prints no credentials. Keep the file
out of Git. Preserve the same signing secret when refreshing tokens; rotating it invalidates
all earlier tokens. Set `PM_PROVIDER=stub` for deterministic no-model-call startup.

The integrated setup needs separate nurse and PSW tokens. The credential writer accepts a
bootstrap JSON object with `nurse` and `psw` tokens on stdin and updates the file without printing
them. Use the explicit startup helper to capture bootstrap JSON privately and populate both roles:

```sh
bash deploy/start-demo.sh first
# Later, refresh expiring tokens without deleting or reloading any checks:
bash deploy/start-demo.sh refresh
```

The first command builds, migrates, bootstraps, loads the cohort and starts the services. It refuses
an already running worker rather than racing an existing deployment. Refresh keeps the signing
secret and existing data. Startup validates both seeded identities and fails if a nurse token is
substituted for PSW. Never run these scripts with shell tracing enabled.

It also provisions the separate fictional KAZE tenant and starts `kaze-worker` as that tenant's
service principal. The KAZE person's token/ID are refreshed privately alongside nurse/PSW tokens;
the service token is not exposed. This setup creates no contacts, sessions or consent decisions.
The assigned KAZE person can explicitly grant, decline or withdraw their own standing voice
permission on `/out`. Unknown blocks capture. Session arming/ending does not change permission.
For fictional fixtures only, the separate setup command remains available:

```sh
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml run --rm -T \
  kaze-bootstrap python -m scripts.hosted_demo kaze-bootstrap --grant-fixture-consent
```

This grants only absent synthetic consent; reload never replaces a withdrawal or decline. It
does not consent for a real person. Unknown consent blocks capture until a recorded decision is
made. The default sender logs offline and sends
no real SMS. Scheduling runs every 15 seconds and 24-hour session retention runs every 60 seconds
between ingestion passes. Verify both `worker` and `kaze-worker` are running.

## First setup order

1. Build the reviewed image.
2. Start only database and object storage; migrate the schema.
3. Bootstrap synthetic identities and create the private nurse/PSW credentials.
4. Load/reset the scripted synthetic cohort before starting the long-running worker. The
   loader processes its own source jobs and refuses contaminated seed data or verdict mismatches.
5. Start/recreate the API with the configured tokens and roster, then start worker and Caddy.
6. Wait for model warm-up and readiness. First boot downloads Whisper; a successful healthcheck
   alone does not establish that transcription or the latency target passed.

Use a reset script for subsequent demos. Never use `docker compose down -v` to refresh a demo
that may contain consenting teammate recordings. A plain cohort reload is not a destructive reset
and deliberately refuses to overwrite unrelated checks.

The loader supports explicit historical prefixes or full history. The merged current-date reset
below restores the intended twelve scripted states and separately provisions live/runner people.
Hosted timing and stage acceptance remain unverified. See decision 008.

## Verification and audio handoff

Verify the HTTPS URL serves pages and API from the same origin, the session roster has twelve
residents, the nurse sees the intended ranking, PSW responses contain no risk data, and evidence
and SBAR citations open real synthetic source spans. Check invalid token/Host/Origin and foreign
patient requests are rejected. Confirm the worker is alive and data survives API restart.

Next, with consenting recordings available, test Safari MP4 and Chrome WebM on phones using LTE,
not only the VM's internal requests. Measure warmed upload-to-result p95 against the five-second
target; record sample count, model, CPU resources and release SHA. Verify runner enrollment,
exertion context/suppression and the labelled backup. Audio remains on hold until Dee resumes it.

KAZE acceptance additionally needs a real missed-check ? SMS ? acknowledgement loop on two
phones with neutral wording, scoped location and proven expiry/deletion. Stub delivery and a
browser-only preview do not establish that loop.

After acceptance, record the backup video, save it in two places and perform two timed solo
rehearsals. Public repo/Devpost submission remain explicit human release steps.

## Shutdown

Stop Caddy/API/workers after the demonstration, then stop the VM when it is no longer needed.
Keep volumes until a deliberate retention/reset decision; verify any ongoing storage/IP charges
with the provider. Revoke deployment secrets when retiring the host.

References: [Google Cloud free program](https://docs.cloud.google.com/free/docs/free-cloud-features),
[Compute Engine Linux instances](https://docs.cloud.google.com/compute/docs/create-linux-vm-instance),
[Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/),
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).


## One-command current-day core demo reset (BL-21)

After private `.env.demo` setup and the reviewed image prerequisites, run:

```sh
bash deploy/reset-demo.sh
# For a repeatable chosen UTC anchor:
bash deploy/reset-demo.sh 2026-10-18T14:00:00Z
```

This refreshes private nurse, PSW and KAZE tokens to 48 hours, restores the twelve scripted story prefixes
at one current/chosen UTC instant, verifies their actual canonical outcomes, and prints `/unit`,
the PSW `/check` and a dedicated live-check URL. A separate runner URL is also printed. The unit
roster can include the two explicitly named capture volunteers in addition to the twelve scripted
residents; the scripted PSW due cohort stays separate. No credentials are printed.

Original fixture files and the existing all-history/scenario-snapshots loader modes are unchanged.
The reset accepts only exact authored fixture rows. It refuses real/runner/session checks or other
unrecognized data inside the scripted identities, rather than deleting them. Existing capture
volunteers, other patients/tenants, consent withdrawals and revoked assignments are preserved.

Creating the dedicated live/runner identities does not record consent. Their initial consent is
unknown and capture returns `403 consent_required` until the authorized care team records the
volunteer's actual decision through the existing consent endpoint. Reset never grants or restores
that consent. The authored, non-audio cohort uses explicit synthetic fixture consent separately.
Use the printed live/runner URLs to keep new recordings outside the scripted identities.

API and the resident worker are stopped before reset to prevent concurrent admissions. The
separate safety worker continues its tenant's retention work and is recreated with the rebuilt
image at startup. Once migration and private token preparation have succeeded, a refused or failed
reset attempts the normal readiness-checked service restart and still exits with the original
reset failure status. A successful recovery means services restarted, not that the fixture reset
passed. Inspect the safe error and ignored reset report, resolve the discrepancy and rerun; the
strict guard remains authoritative. Do not wipe volumes or bypass fixture validation. Same
explicit-anchor reruns preserve data counts and are idempotent.

If service recovery fails, the wrapper reports its separate status and says availability is
unconfirmed; the command still returns the original reset error. Inspect Compose service status
and readiness locally before deciding on another restart. Failures before the reset command
(including migration or private token preparation) do **not** automatically restart services:
inspect and resolve the schema/configuration failure first. Do not blindly start an API against
a failed migration or describe a partially completed reset as successful.
Live phone audio, public DNS/certificates and host latency are still separate acceptance gates.
