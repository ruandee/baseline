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
ARGS=()
[ -z "${1:-}" ] || ARGS=(--demo-at "$1")
# load supplies the admin setup role and ignored artifacts volume; no running worker races it.
"${C[@]}" run --rm -T load python -m scripts.demo_reset "${ARGS[@]}"
"${C[@]}" up -d --wait --wait-timeout 600 --force-recreate api worker caddy
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
