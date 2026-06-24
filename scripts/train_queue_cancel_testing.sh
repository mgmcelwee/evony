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
HAS_QUEUE=$(curl -sS "$BASE/openapi.json" | jq -r --arg p "/cities/{city_id}/train/queue" '.paths | has($p)')
[ "$HAS_QUEUE" = "true" ] || die "Missing route: /cities/{city_id}/train/queue"

HAS_CANCEL=$(
  curl -sS "$BASE/openapi.json" \
    | jq -r --arg p "/cities/{city_id}/train/queue/{queue_id}/cancel" '.paths | has($p)'
)
[ "$HAS_CANCEL" = "true" ] || die "Missing route: POST /cities/{city_id}/train/queue/{queue_id}/cancel"

echo "== Snapshot troops + resources before =="
BEFORE_TROOPS=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" \
    | jq -r --arg c "$CODE" '.troops[]? | select(.code==$c) | .count' | head -n1
)
BEFORE_TROOPS="${BEFORE_TROOPS:-0}"
[[ "$BEFORE_TROOPS" =~ ^[0-9]+$ ]] || die "Could not parse BEFORE troop count (got=$BEFORE_TROOPS)"
echo "before_troops=$BEFORE_TROOPS"

CITY_BEFORE=$(curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/cities/$CITY_ID")
BEFORE_FOOD=$(echo "$CITY_BEFORE" | jq -r '.resources.food')
BEFORE_WOOD=$(echo "$CITY_BEFORE" | jq -r '.resources.wood')
BEFORE_STONE=$(echo "$CITY_BEFORE" | jq -r '.resources.stone')
BEFORE_IRON=$(echo "$CITY_BEFORE" | jq -r '.resources.iron')
echo "before_resources food=$BEFORE_FOOD wood=$BEFORE_WOOD stone=$BEFORE_STONE iron=$BEFORE_IRON"

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

COST_FOOD=$(echo "$BODY" | jq -r '.queued[0].cost.food // 0')
COST_WOOD=$(echo "$BODY" | jq -r '.queued[0].cost.wood // 0')
COST_STONE=$(echo "$BODY" | jq -r '.queued[0].cost.stone // 0')
COST_IRON=$(echo "$BODY" | jq -r '.queued[0].cost.iron // 0')

AFTER_ENQ_FOOD=$(echo "$BODY" | jq -r '.resources_after.food')
AFTER_ENQ_WOOD=$(echo "$BODY" | jq -r '.resources_after.wood')
AFTER_ENQ_STONE=$(echo "$BODY" | jq -r '.resources_after.stone')
AFTER_ENQ_IRON=$(echo "$BODY" | jq -r '.resources_after.iron')

[ -n "$QID" ] || die "Could not read queued[0].id"
[ -n "$SECONDS_TOTAL" ] || die "Could not read queued[0].seconds_total"
echo "queue_id=$QID seconds_total=$SECONDS_TOTAL"
echo "enqueue_cost food=$COST_FOOD wood=$COST_WOOD stone=$COST_STONE iron=$COST_IRON"
echo "after_enqueue_resources food=$AFTER_ENQ_FOOD wood=$AFTER_ENQ_WOOD stone=$AFTER_ENQ_STONE iron=$AFTER_ENQ_IRON"

echo "== Verify queue row is training =="
QSTATUS=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/train/queue" \
    | jq -r --argjson id "$QID" '.queue[]? | select(.id==$id) | .status' | head -n1
)
[ "$QSTATUS" = "training" ] || die "Expected queue id=$QID status=training (got=$QSTATUS)"

echo "== Cancel the queue item =="
CFILE=$(mktemp)
CSTATUS=$(
  curl -sS -o "$CFILE" -w "%{http_code}" \
    -X POST "$BASE/cities/$CITY_ID/train/queue/$QID/cancel" \
    -H "Authorization: Bearer $TOKEN"
)
CBODY=$(cat "$CFILE"); rm -f "$CFILE"
if [ "$CSTATUS" != "200" ]; then
  echo "Cancel failed (status=$CSTATUS):"
  echo "$CBODY" | jq . 2>/dev/null || echo "$CBODY"
  die "Cancel request failed"
fi
echo "$CBODY" | jq .

CANCEL_STATUS=$(echo "$CBODY" | jq -r '.status // empty')
[ "$CANCEL_STATUS" = "cancelled" ] || die "Expected cancel status=cancelled (got=$CANCEL_STATUS)"

AFTER_CAN_FOOD=$(echo "$CBODY" | jq -r '.resources_after.food')
AFTER_CAN_WOOD=$(echo "$CBODY" | jq -r '.resources_after.wood')
AFTER_CAN_STONE=$(echo "$CBODY" | jq -r '.resources_after.stone')
AFTER_CAN_IRON=$(echo "$CBODY" | jq -r '.resources_after.iron')
echo "after_cancel_resources food=$AFTER_CAN_FOOD wood=$AFTER_CAN_WOOD stone=$AFTER_CAN_STONE iron=$AFTER_CAN_IRON"

echo "== Verify refund math (deterministic) =="
EXP_FOOD=$((AFTER_ENQ_FOOD + COST_FOOD))
EXP_WOOD=$((AFTER_ENQ_WOOD + COST_WOOD))
EXP_STONE=$((AFTER_ENQ_STONE + COST_STONE))
EXP_IRON=$((AFTER_ENQ_IRON + COST_IRON))

# Note: if you clamp to max storage on refund, these might cap.
# In Age 1 you’re far from caps, so exact equality is expected.
[ "$AFTER_CAN_FOOD" -eq "$EXP_FOOD" ] || die "Refund food mismatch (expected=$EXP_FOOD got=$AFTER_CAN_FOOD)"
[ "$AFTER_CAN_WOOD" -eq "$EXP_WOOD" ] || die "Refund wood mismatch (expected=$EXP_WOOD got=$AFTER_CAN_WOOD)"
[ "$AFTER_CAN_STONE" -eq "$EXP_STONE" ] || die "Refund stone mismatch (expected=$EXP_STONE got=$AFTER_CAN_STONE)"
[ "$AFTER_CAN_IRON" -eq "$EXP_IRON" ] || die "Refund iron mismatch (expected=$EXP_IRON got=$AFTER_CAN_IRON)"

echo "== Verify queue row is cancelled (and remains) =="
QSTATUS2=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/train/queue" \
    | jq -r --argjson id "$QID" '.queue[]? | select(.id==$id) | .status' | head -n1
)
[ "$QSTATUS2" = "cancelled" ] || die "Expected queue id=$QID status=cancelled (got=$QSTATUS2)"

echo "== Wait past original finish time and tick-on-read; troops should NOT increase =="
sleep $((SECONDS_TOTAL + WAIT_PAD))

AFTER_TROOPS=$(
  curl -sS -H "Authorization: Bearer $TOKEN" \
    "$BASE/cities/$CITY_ID/troops" \
    | jq -r --arg c "$CODE" '.troops[]? | select(.code==$c) | .count' | head -n1
)
AFTER_TROOPS="${AFTER_TROOPS:-0}"
[[ "$AFTER_TROOPS" =~ ^[0-9]+$ ]] || die "Could not parse AFTER troop count (got=$AFTER_TROOPS)"
echo "after_troops=$AFTER_TROOPS"
[ "$AFTER_TROOPS" -eq "$BEFORE_TROOPS" ] || die "Expected no troop increase after cancel (before=$BEFORE_TROOPS after=$AFTER_TROOPS)"

ok "Queued training cancellation UI-test passed"

