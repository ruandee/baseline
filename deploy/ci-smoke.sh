#!/usr/bin/env bash
# BL-20 container smoke for CI: builds the demo image and runs the documented sequence against
# a throwaway localhost stack (Caddy internal CA, no public DNS). Synthetic data only; the audio
# is an ffmpeg-generated tone that exercises decode/VAD/Whisper/storage plumbing, not speech.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE=.env.demo
if [ -e "$ENV_FILE" ]; then echo "refusing to overwrite existing $ENV_FILE" >&2; exit 1; fi
cat > "$ENV_FILE" <<EOF
PM_DEMO_DOMAIN=localhost
PM_FRONTEND_HOSTS=localhost
PM_JWT_SECRET=$(openssl rand -hex 32)
PM_DEMO_TOKEN=
PM_DEMO_PSW_TOKEN=
PM_PROVIDER=stub
PM_RATE_LIMIT=600
PM_WHISPER_MODEL=tiny
PM_KEEP_AUDIO=false
EOF
C=(docker compose --env-file "$ENV_FILE" -f compose.yaml -f compose.demo.yaml)
BASE=https://localhost
TMP=${RUNNER_TEMP:-$(mktemp -d)}
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }
status() { curl -sk -o /dev/null -w '%{http_code}' "$@"; }

"${C[@]}" build
"${C[@]}" up -d --wait db object-store
"${C[@]}" run --rm -T migrate
CREDENTIALS=$("${C[@]}" run --rm -T bootstrap python -m scripts.hosted_demo bootstrap --json)
TOKEN=$(jq -er .nurse <<<"$CREDENTIALS")
PSW_TOKEN=$(jq -er .psw <<<"$CREDENTIALS")
unset CREDENTIALS
[ -n "$TOKEN" ] || fail "bootstrap printed no token"
KAZE_CREDENTIALS=$("${C[@]}" run --rm -T kaze-bootstrap python -m scripts.hosted_demo kaze-bootstrap --json)
printf '%s' "$KAZE_CREDENTIALS" | python3 -m scripts.prepare_deployment kaze-credentials
KAZE_TOKEN=$(jq -er .kaze <<<"$KAZE_CREDENTIALS")
KAZE_PID=$(jq -er .kaze_patient_id <<<"$KAZE_CREDENTIALS")
unset KAZE_CREDENTIALS

# Guards: each refusal must exit nonzero within 60 s AND name the reason on its output.
refuse() {
  local expect=$1 out; shift
  if out=$(timeout 60 "${C[@]}" run --rm -T "$@" 2>&1); then fail "guard did not refuse: $expect"; fi
  grep -qF -- "$expect" <<<"$out" || { tail -n 20 <<<"$out" >&2; fail "guard output lacked: $expect"; }
  echo "guard ok: $expect"
}
SERVE=(api python -m scripts.hosted_demo serve)
refuse "admin credentials" -e PM_DEMO_TOKEN="$TOKEN"   -e PM_ADMIN_DATABASE_URL=postgresql://postgres:synthetic-admin@db:5432/patient_memory "${SERVE[@]}"
refuse "explicit hostnames" -e PM_DEMO_TOKEN="$TOKEN" -e PM_FRONTEND_HOSTS='*' "${SERVE[@]}"
refuse "PM_DEMO_TOKEN must be" "${SERVE[@]}"
refuse "deployment-only PM_JWT_SECRET" -e PM_DEMO_TOKEN="$TOKEN"   -e PM_JWT_SECRET=synthetic-local-only-change-before-any-deployment "${SERVE[@]}"

sed -i "s|^PM_DEMO_TOKEN=.*|PM_DEMO_TOKEN=$TOKEN|;s|^PM_DEMO_PSW_TOKEN=.*|PM_DEMO_PSW_TOKEN=$PSW_TOKEN|" "$ENV_FILE"
"${C[@]}" up -d --wait --wait-timeout 600 api caddy
"${C[@]}" exec -T api python -m scripts.hosted_demo check

# Only Caddy is published: the API port must not answer on the host.
if curl -s --max-time 3 http://127.0.0.1:8001/v1/health/live; then fail "API port published"; fi

[ "$(status "$BASE/check")" = 200 ] || fail "/check page not served over HTTPS"
[ "$(status "$BASE/assets/baseline.js")" = 200 ] || fail "frontend assets not same-origin"
SESSION=$(curl -fsSk -H 'X-PM-Demo: 1' -H "Origin: $BASE" "$BASE/demo/session")
[ "$(jq -r .token <<<"$SESSION")" = "$TOKEN" ] || fail "session did not serve the pre-minted token"
roster() { curl -fsSk -H 'X-PM-Demo: 1' -H "Origin: $BASE" "$BASE/demo/session" | jq '.patients | length'; }
[ "$(roster)" = 6 ] || fail "bootstrap roster is not the six seeded residents"
PID=$(jq -r '.patients[0].id' <<<"$SESSION")

# Scheme comes from Caddy's X-Forwarded-Proto: an http Origin must be rejected.
[ "$(status -H 'X-PM-Demo: 1' -H 'Origin: http://localhost' "$BASE/demo/session")" = 403 ] \
  || fail "http origin accepted"
[ "$(status -H 'X-PM-Demo: 1' -H 'Origin: https://evil.example.com' "$BASE/demo/session")" = 403 ] \
  || fail "foreign origin accepted"
[ "$(status "$BASE/demo/session")" = 403 ] || fail "session served without demo header"
"${C[@]}" exec -T api python -c "
import urllib.error, urllib.request
r = urllib.request.Request('http://127.0.0.1:8001/demo/session',
                           headers={'Host': 'evil.example.com', 'X-PM-Demo': '1'})
try:
    urllib.request.urlopen(r, timeout=5)
except urllib.error.HTTPError as e:
    assert e.code == 403, e.code
else:
    raise SystemExit('foreign Host accepted')
"
[ "$(status -H 'Authorization: Bearer not-a-token' "$BASE/v1/watchlist")" = 401 ] \
  || fail "invalid bearer not rejected"
[ "$(status -H "Authorization: Bearer $TOKEN" -H "Origin: $BASE" \
     "$BASE/v1/patients/00000000-0000-0000-0000-000000000000/overview")" = 404 ] \
  || fail "unassigned patient not 404"
[ "$(status -H "Authorization: Bearer $TOKEN" "$BASE/v1/patients/$KAZE_PID/sessions")" = 404 ] \
  || fail "resident tenant could read KAZE sessions"
curl -fsSk -H "Authorization: Bearer $KAZE_TOKEN" "$BASE/v1/patients/$KAZE_PID/consent" \
  | jq -e '.state == "unknown"' >/dev/null || fail "KAZE bootstrap silently granted consent"
curl -fsSk -H "Authorization: Bearer $KAZE_TOKEN" "$BASE/v1/patients/$KAZE_PID/sessions" \
  | jq -e '.sessions | length == 0' >/dev/null || fail "KAZE bootstrap armed a session"

# BL-14 loader in the image: one-off admin step, then recreate api to pick up the roster.
timeout 900 "${C[@]}" run --rm -T load
"${C[@]}" up -d --wait --wait-timeout 600 --force-recreate api
[ "$(roster)" = 12 ] || fail "hosted roster is not the 12 loaded residents"
echo "roster after load: 12"
PSW_SESSION=$(curl -fsSk -H 'X-PM-Demo: 1' -H 'X-PM-Role: psw' -H "Origin: $BASE" "$BASE/demo/session")
[ "$(jq -r .token <<<"$PSW_SESSION")" = "$PSW_TOKEN" ] || fail "PSW session token mismatch"
[ "$(status -H "Authorization: Bearer $PSW_TOKEN" "$BASE/v1/watchlist")" = 404 ] || fail "PSW read risk data"
curl -fsSk -H "Authorization: Bearer $PSW_TOKEN" "$BASE/v1/checks/due" > "$TMP/due.json"
jq -e '.residents | length == 12' "$TMP/due.json" >/dev/null || fail "PSW roster missing residents"
jq -e 'all(.residents[]; (has("fused_z") or has("verdict") or has("latest_verdict") or has("sbar")) | not)' "$TMP/due.json" >/dev/null || fail "PSW due list leaked risk data"


# Load only into pristine seeded patients; uploads intentionally make loader preflight fail.
SESSION=$(curl -fsSk -H 'X-PM-Demo: 1' -H "Origin: $BASE" "$BASE/demo/session")
PID=$(jq -r '.patients[0].id' <<<"$SESSION")

# Upload plumbing through Caddy: ffmpeg decode, VAD, Whisper (tiny), storage. Not validation.
"${C[@]}" exec -T api ffmpeg -nostdin -loglevel error -f lavfi -i sine=frequency=220:duration=8 \
  -c:a libopus -f webm - > "$TMP/tone.webm"
CODE=$(curl -sk -o "$TMP/check.json" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" -H "Origin: $BASE" \
  -F "audio=@$TMP/tone.webm;type=audio/webm" -F mode=resident -F device_id=ci-smoke \
  "$BASE/v1/patients/$PID/checks")
echo "upload status $CODE: $(head -c 600 "$TMP/check.json")"
[ "$CODE" = 200 ] || fail "check upload through Caddy failed"
jq -e '.timings_ms.asr | numbers' "$TMP/check.json" >/dev/null || fail "upload did not run ASR"


# The loader drains its own source jobs; start the long-running consumer afterwards.
"${C[@]}" up -d --wait worker kaze-worker
sleep 3
[ -n "$("${C[@]}" ps --status running -q worker)" ] || fail "worker not running"
if "${C[@]}" logs worker | grep -q Traceback; then fail "worker raised"; fi
[ -n "$("${C[@]}" ps --status running -q kaze-worker)" ] || fail "KAZE worker not running"
if "${C[@]}" logs kaze-worker | grep -q Traceback; then fail "KAZE worker raised"; fi
echo "SMOKE OK"
