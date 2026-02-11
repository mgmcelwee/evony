#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
CITY_ID="${CITY_ID:-3}"
CODE="${CODE:-t1_inf}"
ADD="${ADD:-10}"

die() { echo "❌ $*" >&2; exit 1; }
ok() { echo "✅ $*"; }

echo "== Login Alicia =="
TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed (token empty/null)"

echo "== Read troop count before =="
BEFORE=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" | jq -r --arg c "$CODE" '.troops[] | select(.code==$c) | .count' | head -n1
)
BEFORE="${BEFORE:-0}"
[[ "$BEFORE" =~ ^[0-9]+$ ]] || die "Could not parse BEFORE count (got=$BEFORE)"
echo "before=$BEFORE"

echo "== Preview train =="
curl -sS -X POST "$BASE/cities/$CITY_ID/train/preview" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":$ADD}]}" | jq .

echo "== Train troops =="
RESP=$(curl -sS -X POST "$BASE/cities/$CITY_ID/train" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":$ADD}]}")
echo "$RESP" | jq .

echo "== Read troop count after =="
AFTER=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" | jq -r --arg c "$CODE" '.troops[] | select(.code==$c) | .count' | head -n1
)
AFTER="${AFTER:-0}"
[[ "$AFTER" =~ ^[0-9]+$ ]] || die "Could not parse AFTER count (got=$AFTER)"
echo "after=$AFTER"

EXPECTED=$((BEFORE + ADD))
[ "$AFTER" -eq "$EXPECTED" ] || die "Expected $CODE to be $EXPECTED (got=$AFTER)"

ok "Training UI-test passed"
