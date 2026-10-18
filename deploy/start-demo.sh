#!/usr/bin/env bash
# Explicit synthetic setup/token refresh; no data deletion and no credentials on stdout.
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=${1:-}
case "$MODE" in first|refresh) ;; *) echo 'Usage: bash deploy/start-demo.sh first|refresh' >&2; exit 2;; esac
[ -f .env.demo ] || { echo 'Initialize .env.demo with scripts.prepare_deployment first.' >&2; exit 1; }
C=(docker compose --env-file .env.demo -f compose.yaml -f compose.demo.yaml)
"${C[@]}" config --quiet
if [ "$MODE" = first ]; then
  [ -z "$("${C[@]}" ps --status running -q worker)" ] || { echo 'Worker already running; use the reset workflow for an existing demo.' >&2; exit 1; }
  "${C[@]}" build
  "${C[@]}" up -d --wait db object-store
  "${C[@]}" run --rm -T migrate
fi
CREDENTIALS=$("${C[@]}" run --rm -T bootstrap python -m scripts.hosted_demo bootstrap --json)
printf '%s' "$CREDENTIALS" | python3 -m scripts.prepare_deployment credentials
unset CREDENTIALS
if [ "$MODE" = first ]; then
  "${C[@]}" run --rm -T load
fi
"${C[@]}" up -d --wait --wait-timeout 600 --force-recreate api worker caddy
python3 - <<'PY'
from pathlib import Path
values = dict(line.split('=', 1) for line in Path('.env.demo').read_text().splitlines()
              if line and not line.startswith('#') and '=' in line)
base = 'https://' + values['PM_DEMO_DOMAIN']
print('Services started; verify public HTTPS and real-phone acceptance separately:')
for path in ('/unit', '/check', '/check?mode=live'):
    print(base + path)
PY
