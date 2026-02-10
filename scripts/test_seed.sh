#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
CITY_ID="${CITY_ID:-3}"
ADMIN_KEY="${ADMIN_KEY:-Mathew-evony-admin-9f3c7d2a11}"
INF_COUNT="${INF_COUNT:-200}"
RNG_COUNT="${RNG_COUNT:-200}"

die() { echo "❌ $*" >&2; exit 1; }

echo "== Login Alicia =="
TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed (token empty/null)"

echo "== Confirm seed endpoint exists =="
# This will fail loudly if /openapi.json isn't reachable
HAS_ROUTE=$(curl -sS "$BASE/openapi.json" | jq -r --arg p "/cities/{city_id}/troops/set" '.paths | has($p)')
[ "$HAS_ROUTE" = "true" ] || die "Missing route: POST /cities/{city_id}/troops/set (restart server or add endpoint)"

echo "== Seed troops on City $CITY_ID =="
BODYFILE=$(mktemp)
STATUS=$(
  curl -sS -o "$BODYFILE" -w "%{http_code}" \
    -X POST "$BASE/cities/$CITY_ID/troops/set" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"troops\":[{\"code\":\"t1_inf\",\"count\":$INF_COUNT},{\"code\":\"t1_rng\",\"count\":$RNG_COUNT}]}"
)
BODY=$(cat "$BODYFILE"); rm -f "$BODYFILE"

if [ "$STATUS" != "200" ]; then
  echo "Seed failed (status=$STATUS):"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
  die "Seeding troops failed"
fi

echo "$BODY" | jq .
echo "✅ seeded"

echo "== Verify troops now =="
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE/cities/$CITY_ID/troops" | jq '.totals, (.troops | map({code,count}) | sort_by(.code))'
