#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"
CITY_ID="${CITY_ID:-3}"
CODE="${CODE:-t1_inf}"
ADD="${ADD:-5}"
WAIT_PAD="${WAIT_PAD:-2}"

die() { echo "❌ $*" >&2; exit 1; }
ok() { echo "✅ $*"; }

echo "== Login Alicia =="
TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed (token empty/null)"

echo "== Confirm training queue routes exist =="
HAS_POST=$(curl -sS "$BASE/openapi.json" | jq -r --arg p "/cities/{city_id}/train/queue" '.paths | has($p)')
[ "$HAS_POST" = "true" ] || die "Missing route: POST /cities/{city_id}/train/queue"
HAS_GET=$(curl -sS "$BASE/openapi.json" | jq -r --arg p "/cities/{city_id}/train/queue" '.paths[$p] | has("get")')
[ "$HAS_GET" = "true" ] || die "Missing route: GET /cities/{city_id}/train/queue"

echo "== Read troop count before =="
BEFORE=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" | jq -r --arg c "$CODE" '.troops[]? | select(.code==$c) | .count' | head -n1
)
BEFORE="${BEFORE:-0}"
[[ "$BEFORE" =~ ^[0-9]+$ ]] || die "Could not parse BEFORE count (got=$BEFORE)"
echo "before=$BEFORE"

echo "== Enqueue training (queue) =="
BODYFILE=$(mktemp)
STATUS=$(
  curl -sS -o "$BODYFILE" -w "%{http_code}" \
    -X POST "$BASE/cities/$CITY_ID/train/queue" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"troops\":[{\"code\":\"$CODE\",\"count\":$ADD}]}"
)
BODY=$(cat "$BODYFILE"); rm -f "$BODYFILE"
if [ "$STATUS" != "200" ]; then
  echo "Queue failed (status=$STATUS):"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
  die "Queue request failed"
fi

echo "$BODY" | jq .
QID=$(echo "$BODY" | jq -r '.queued[0].id // empty')
SECONDS_TOTAL=$(echo "$BODY" | jq -r '.queued[0].seconds_total // empty')
[ -n "$QID" ] || die "Could not read queued[0].id"
[ -n "$SECONDS_TOTAL" ] || die "Could not read queued[0].seconds_total"
echo "queue_id=$QID seconds_total=$SECONDS_TOTAL"

echo "== Verify queue row is training =="
QSTATUS=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/train/queue" | jq -r --argjson id "$QID" '.queue[]? | select(.id==$id) | .status' | head -n1
)
[ "$QSTATUS" = "training" ] || die "Expected queue id=$QID status=training (got=$QSTATUS)"

echo "== Verify troop count does NOT change immediately =="
NOW_COUNT=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" | jq -r --arg c "$CODE" '.troops[]? | select(.code==$c) | .count' | head -n1
)
NOW_COUNT="${NOW_COUNT:-0}"
[[ "$NOW_COUNT" =~ ^[0-9]+$ ]] || die "Could not parse NOW count (got=$NOW_COUNT)"
echo "now=$NOW_COUNT"
[ "$NOW_COUNT" -eq "$BEFORE" ] || die "Expected no immediate troop increase (before=$BEFORE now=$NOW_COUNT)"

echo "== Wait for completion (sleep seconds_total + pad) =="
sleep $((SECONDS_TOTAL + WAIT_PAD))

echo "== Trigger tick-on-read and verify increased =="
AFTER=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" | jq -r --arg c "$CODE" '.troops[]? | select(.code==$c) | .count' | head -n1
)
AFTER="${AFTER:-0}"
[[ "$AFTER" =~ ^[0-9]+$ ]] || die "Could not parse AFTER count (got=$AFTER)"
echo "after=$AFTER"

EXPECTED=$((BEFORE + ADD))
[ "$AFTER" -eq "$EXPECTED" ] || die "Expected $CODE to be $EXPECTED (got=$AFTER)"

echo "== Verify queue row becomes completed (and remains) =="
QSTATUS2=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/train/queue" | jq -r --argjson id "$QID" '.queue[]? | select(.id==$id) | .status' | head -n1
)
[ "$QSTATUS2" = "completed" ] || die "Expected queue id=$QID status=completed (got=$QSTATUS2)"

ok "Queued training UI-test passed"

