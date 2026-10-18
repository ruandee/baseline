#!/usr/bin/env bash
# Explicit synthetic fixture reset; real/live/runner data are never deletion targets.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env.demo ] || { echo 'Initialize private .env.demo first; see docs/deployment-path.md.' >&2; exit 1; }
# Server-side profile, before reading Compose configuration or changing running services.
python3 -m scripts.prepare_deployment runner-profile
C=(docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml)
"${C[@]}" config --quiet
"${C[@]}" stop api worker
"${C[@]}" up -d --wait db object-store
"${C[@]}" build
"${C[@]}" run --rm -T migrate
CREDENTIALS=$("${C[@]}" run --rm -T -e PM_TOKEN_TTL_HOURS=48 bootstrap python -m scripts.hosted_demo bootstrap --json)
printf '%s' "$CREDENTIALS" | python3 -m scripts.prepare_deployment credentials
unset CREDENTIALS
# Refresh the separate self-custody identity without granting consent or creating sessions.
KAZE_CREDENTIALS=$("${C[@]}" run --rm -T -e PM_TOKEN_TTL_HOURS=48 kaze-bootstrap python -m scripts.hosted_demo kaze-bootstrap --json)
printf '%s' "$KAZE_CREDENTIALS" | python3 -m scripts.prepare_deployment kaze-credentials
unset KAZE_CREDENTIALS
ARGS=()
[ -z "${1:-}" ] || ARGS=(--demo-at "$1")
# load supplies the admin setup role and ignored artifacts volume; no running worker races it.
start_services() {
  "${C[@]}" up -d --wait --wait-timeout 600 --force-recreate api worker kaze-worker caddy
}
# Recovery is limited to the reset command: migration and private credential preparation
# must have completed successfully before an API can safely use the resulting schema/config.
if "${C[@]}" run --rm -T load python -m scripts.demo_reset "${ARGS[@]}"; then
  start_services
else
  reset_status=$?
  echo 'Reset failed; attempting service recovery. Data was not certified as reset.' >&2
  if start_services; then
    echo 'Services restarted; reset still failed. Inspect the reset error/report before retrying.' >&2
  else
    recovery_status=$?
    printf 'Service recovery failed (status %s); API/worker availability is unconfirmed. Inspect locally.\n' "$recovery_status" >&2
  fi
  exit "$reset_status"
fi
python3 - <<'PY'
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
def uid(name):
    return uuid5(NAMESPACE_URL, "patient-memory/synthetic/" + name)
values = dict(line.split('=', 1) for line in Path('.env.demo').read_text().splitlines()
              if line and not line.startswith('#') and '=' in line)
base = 'https://' + values['PM_DEMO_DOMAIN']
print('12 scripted residents, plus separate live/runner volunteers whose recordings are preserved.')
for path in ('/unit', '/check', '/check?mode=live&patient=' + str(uid('0/live-capture'))):
    print(base + path)
print('Runner: ' + base + '/check?mode=runner&patient=' + str(uid('0/runner-capture')))
PY
