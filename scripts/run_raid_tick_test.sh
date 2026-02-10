#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
USERNAME="${USERNAME:-mathew}"
PASSWORD="${PASSWORD:-ChangeMe123!}"

echo "== Login -> get token =="

LOGIN_JSON="$(curl -sS -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")"

if [[ -z "${LOGIN_JSON// }" ]]; then
  echo "ERROR: /auth/login returned empty body."
  echo "Check server is up and BASE_URL is correct: $BASE_URL"
  exit 1
fi

# Parse token safely (NO heredoc; read from stdin)
if ! TOKEN="$(python3 -c 'import json,sys
raw=sys.stdin.read()
j=json.loads(raw)
t=j.get("token")
if not t:
    raise SystemExit("missing token")
print(t)
' <<<"$LOGIN_JSON")"; then
  echo "ERROR: login response was not valid JSON or missing token."
  echo "Response body: $LOGIN_JSON"
  exit 1
fi

if [[ -z "${TOKEN:-}" ]]; then
  echo "ERROR: parsed TOKEN was empty."
  echo "Response body: $LOGIN_JSON"
  exit 1
fi

export EVONY_TOKEN="$TOKEN"
export TOKEN="$TOKEN"

echo "Token acquired."
echo "expires_at: $(python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("expires_at"))' <<<"$LOGIN_JSON")"
echo

exec ./scripts/test_raid_tick.sh
