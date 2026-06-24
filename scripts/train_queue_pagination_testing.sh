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
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed"

echo "== Confirm queue route exists =="
HAS_QUEUE=$(curl -sS "$BASE/openapi.json" | jq -r --arg p "/cities/{city_id}/train/queue" '.paths | has($p)')
[ "$HAS_QUEUE" = "true" ] || die "Missing route: GET /cities/{city_id}/train/queue"

echo "== Enqueue 3 items =="
for i in 1 2 3; do
  curl -sS -X POST "$BASE/cities/$CITY_ID/train/queue" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":1}]}" \
    >/dev/null
done

echo "== Page 1 (limit=2) =="
PAGE1=$(curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE/cities/$CITY_ID/train/queue?limit=2")

echo "$PAGE1" | jq .
COUNT1=$(echo "$PAGE1" | jq -r '.count')
NEXT_ID=$(echo "$PAGE1" | jq -r '.next_before_id // empty')

[ "$COUNT1" = "2" ] || die "Expected 2 results on page 1"
[ -n "$NEXT_ID" ] || die "Expected next_before_id"

echo "== Page 2 =="
PAGE2=$(curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE/cities/$CITY_ID/train/queue?limit=2&before_id=$NEXT_ID")

echo "$PAGE2" | jq .
COUNT2=$(echo "$PAGE2" | jq -r '.count')

[ "$COUNT2" -ge "1" ] || die "Expected at least 1 result on page 2"

ok "Training queue pagination UI-test passed"

