# Put the synthetic demo online from a new server

This is the guided version of [deployment-path.md](deployment-path.md). You need one Linux
server and one DNS hostname. The app, database, synthetic object storage, speech tools and HTTPS
proxy all run together on that server. There is no separate frontend hosting account to set up.
These instructions create a synthetic engineering demo, not a real-patient service.

No server, domain or cloud account has been created by this document. Check your credits and
budget before accepting a provider's creation or purchase screen. Use a teammate's existing
domain/subdomain if available; you do not need a second domain just for this app.

## 1. Create the server

If you have Google Cloud credits, use the project that owns them. In Compute Engine, create a
VM with Ubuntu 24.04 LTS, x86_64/amd64 CPU, around 4 vCPUs and 8–16 GiB memory. For example,
`e2-standard-4` supplies 4 vCPUs and 16 GiB. A 50 GB boot disk is a starting allowance for images,
model cache and synthetic data; actual usage needs monitoring. No GPU is required by the code.
This size has not established the five-second latency target.

Choose a region near the people demonstrating. Enable HTTP and HTTPS traffic and use the
provider's supported SSH access. If opening TCP 22 yourself, restrict it to your operator IP.
Do not open ports 8001, 55432 or 59000 to the internet. Keep the provider's displayed cost and
the credits' expiry in view before creating anything.

Reserve a static public IPv4 address and attach it to this VM so DNS does not break after a
restart. Keep that IP handy. Google documents [creating Linux VMs](https://docs.cloud.google.com/compute/docs/create-linux-vm-instance)
and [reserving static addresses](https://docs.cloud.google.com/compute/docs/ip-addresses/configure-static-external-ip-address).
The same Linux/DNS recipe works on another provider; use its firewall and SSH instructions.

## 2. Give it a hostname

In your domain's DNS settings, add an **A** record. Example:

| DNS field | Example value |
| --- | --- |
| Type | A |
| Name/host | `baseline` |
| IPv4/value | Your VM's static public IP |
| Resulting hostname | `baseline.yourdomain.com` |

Use DNS-only routing for this first setup if your DNS provider offers an optional proxy. Do
not add an AAAA record unless the VM has working public IPv6. Do not enter `https://` or `/check`
in the DNS record or app hostname setting.

Wait until `nslookup baseline.yourdomain.com` on your own computer returns the VM's public IP.
Caddy needs public DNS and reachable TCP ports 80 and 443 to obtain its certificate. It then
handles HTTPS and renewal automatically. Do not install a second nginx/Apache/Caddy service on
the VM; the repository includes Caddy in Compose. See [Caddy's HTTPS prerequisites](https://caddyserver.com/docs/quick-starts/https).

## 3. Install Docker on the VM

Open the VM's SSH terminal. Everything below runs **on the Ubuntu VM**, not in Windows
PowerShell on your laptop. For a fresh Ubuntu machine, use Docker's official apt repository:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3 gh
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Disconnect SSH, then reconnect so the group membership takes effect. Docker group membership
grants administrative control of the VM, so use a dedicated team-controlled account. Verify:

```bash
docker info >/dev/null
docker compose version
```

If the VM already has Docker or a conflicting package, follow the official
[Ubuntu installation instructions](https://docs.docker.com/engine/install/ubuntu/) and
[Linux post-install steps](https://docs.docker.com/engine/install/linux-postinstall/) before
continuing. The helper scripts expect `docker` to work as your SSH user. You do not need to
install uv, Node, FFmpeg, Whisper or project Python packages on the host.

## 4. Copy the private repository

Authenticate using GitHub's device flow; follow the URL/code in the terminal privately:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
git clone https://github.com/ruandee/patient-memory-backend.git
cd patient-memory-backend
```

Your account needs access to this private repository. Do not put a personal access token in a
clone URL, paste it into chat, or make the repository public to fix an authentication error.

Check out the **reviewed release SHA supplied after integrated CI passes**:

```bash
git checkout RELEASE_SHA
bash deploy/check-host.sh
```

Replace `RELEASE_SHA` with that actual commit. It is intentionally not fixed here while
integration continues. Do not deploy a moving mixture of unfinished feature branches.

## 5. Initialize and start

Replace the example hostname with your real DNS hostname:

```bash
python3 -m scripts.prepare_deployment init baseline.yourdomain.com
bash deploy/start-demo.sh first
```

The initializer creates an owner-only `.env.demo` with a random signing secret. The startup
helper builds images, starts storage, migrates, bootstraps separate nurse/PSW credentials,
loads twelve fictional residents, and starts the API, worker and Caddy. It captures credentials
privately; there is no token to copy/paste. First startup downloads the speech model and may
take several minutes. Do not run with `bash -x`, print `.env.demo`, or run an expanded
`docker compose config` into a shared transcript; `config --quiet` is safe for validation.

The default `PM_PROVIDER=stub` uses deterministic offline text generation. Speech still runs
Whisper locally. Keep this setting for initial deployment; configuring a model or SMS provider
is separate work. Keep `PM_KEEP_AUDIO=false`.

Use the startup helper rather than older manual nurse-only bootstrap examples: the current
server requires a distinct PSW token too. The loader must finish before the resident worker
starts. If `first` says a worker is already running, stop and inspect the existing deployment;
do not erase its volumes to make the message disappear.

## 6. Open and verify it

Open these URLs in your own browser:

- `https://baseline.yourdomain.com/unit` — nurse watch list.
- `https://baseline.yourdomain.com/check` — score-free PSW capture and due list.
- `https://baseline.yourdomain.com/check?mode=live` — technical live capture.

Confirm the roster includes twelve scripted residents. Open a resident's evidence and draft, and check that
citations open the corresponding synthetic quote/check. A healthy server alone does not prove
that these flows work. Share the URL only with the demo team: the synthetic nurse demo is
intentionally accessible to anyone who has the URL.

The default loader's `all-history` presentation ends with recovered states. It does not create
the intended current-date Mrs. K/Mr. T/Mrs. L stage snapshot. On the configured host, run:

```bash
bash deploy/reset-demo.sh
```

This restores the current-day scripted scenarios, refreshes private nurse/PSW/KAZE tokens and
prints the demo URLs. It also provisions separate live/runner people, whose recordings remain
outside the scripted deletion allowlist. Their consent starts unknown; record the actual
decision before capture. The twelve scripted residents therefore need not be the entire roster.
A plain loader reload is not a reset and refuses unrelated checks. Time the command on the
actual host: the under-one-minute acceptance gate remains unverified.

When golden recordings are available, verify Safari MP4 and Chrome WebM using phones with
Wi-Fi disabled. Record permission, upload, unusable/error behavior and warm latency must all be
tested. These instructions do not close the golden-audio or real-device gates.

Hosted KAZE worker/bootstrap integration is merged. Startup and reset refresh a separate
safety-tenant person identity and start
`kaze-worker`. It creates no contacts, sessions or consent by default. Follow the release's
`deployment-path.md` for explicit fictional fixture consent before capture; never treat that
setup as consent for a real person. Real SMS remains a separate provider/phone acceptance gate.

## 7. Refresh credentials and diagnose startup

Tokens last 48 hours by default. Before the demonstration, refresh without changing data:

```bash
bash deploy/start-demo.sh refresh
```

`refresh` keeps the signing secret and checks; it is not a code upgrade or schema migration.
For service status and recent logs:

```bash
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml ps
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml logs --tail 100 api caddy worker
```

If HTTPS fails, check public DNS, VM/cloud firewall rules, and whether another service owns
80/443. If startup reports permission denied from Docker, reconnect after the group setup.
If checks return 401 after previously working, refresh credentials. If a load reports existing
recordings or a verdict mismatch, preserve its report and resolve the cause; do not bypass the gate.

## 8. Stop public access after the demo

```bash
docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml stop caddy api worker
```

Also stop `kaze-worker` if the selected release includes it. Stop the VM in the cloud console
when no longer needed; check continuing disk/static-IP charges separately. Keep data volumes
until an intentional reset/retention decision. Do not use `docker compose down -v` to refresh
a demo that might contain teammate recordings. Retire deployment secrets when retiring the host.
