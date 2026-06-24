#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
CITY_ID="${CITY_ID:-3}"
CODE="${CODE:-t1_inf}"

die() { echo "❌ $*" >&2; exit 1; }
ok() { echo "✅ $*"; }

echo "== Login Alicia =="
TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed (token empty/null)"

echo "== Preview 1 unit to learn rules =="
PREVIEW=$(curl -sS -X POST "$BASE/cities/$CITY_ID/train/preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":1}]}")
echo "$PREVIEW" | jq .

MAX_BATCH=$(echo "$PREVIEW" | jq -r '.rules.max_batch')
BARRACKS=$(echo "$PREVIEW" | jq -r '.rules.barracks_level')
MULT=$(echo "$PREVIEW" | jq -r '.rules.cost_multiplier')

[[ "$MAX_BATCH" =~ ^[0-9]+$ ]] || die "Could not parse max_batch"
echo "rules: barracks_level=$BARRACKS max_batch=$MAX_BATCH cost_multiplier=$MULT"

TOO_MANY=$((MAX_BATCH + 1))

echo "== Train TOO MANY ($TOO_MANY) should fail 409 =="
BODYFILE=$(mktemp)
STATUS=$(curl -sS -o "$BODYFILE" -w "%{http_code}" \
  -X POST "$BASE/cities/$CITY_ID/train" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":$TOO_MANY}]}")
BODY=$(cat "$BODYFILE"); rm -f "$BODYFILE"

if [ "$STATUS" != "409" ]; then
  echo "Expected 409 but got $STATUS"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
  die "Batch cap not enforced"
fi
echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
ok "Batch cap enforced"

echo "== Train MAX_BATCH ($MAX_BATCH) should succeed =="
curl -sS -X POST "$BASE/cities/$CITY_ID/train" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":$MAX_BATCH}]}" | jq .

ok "Building-based training rules UI-test passed"

