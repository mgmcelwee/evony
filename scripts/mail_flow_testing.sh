#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:8000"

die() { echo "❌ $*" >&2; exit 1; }

echo "== Login Alicia =="
ALICIA_TOKEN=$(
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
)

[ -n "${ALICIA_TOKEN:-}" ] && [ "$ALICIA_TOKEN" != "null" ] || die "Login failed (token was empty/null)"

echo "== Unread count before =="
BEFORE_JSON=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/unread_count?kind=raid_report")
BEFORE=$(echo "$BEFORE_JSON" | jq -r .unread)
echo "before=$BEFORE"

echo "== Cleanup: recall any active raids for attacker_city_id=3 =="
ACTIVE_IDS=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/raids?status=enroute&limit=200" | jq -r '.raids[].raid_id')

ACTIVE_IDS2=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/raids?status=returning&limit=200" | jq -r '.raids[].raid_id')

for rid in $ACTIVE_IDS $ACTIVE_IDS2; do
  echo "recalling raid_id=$rid"
  curl -sS -X POST -H "Authorization: Bearer $ALICIA_TOKEN" \
    "$BASE/raids/$rid/recall" >/dev/null || true
done

echo "== Create raid =="
# Capture HTTP status + body
CREATE_BODY_FILE=$(mktemp)
CREATE_STATUS=$(
  curl -sS -o "$CREATE_BODY_FILE" -w "%{http_code}" \
    -X POST "$BASE/raids" \
    -H "Authorization: Bearer $ALICIA_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"attacker_city_id":3,"target_city_id":1,"troops":[{"code":"t1_inf","count":10},{"code":"t1_rng","count":5}]}'
)
RESP=$(cat "$CREATE_BODY_FILE")
rm -f "$CREATE_BODY_FILE"

echo "create_status=$CREATE_STATUS"
# If it wasn't 200, show the body and stop.
if [ "$CREATE_STATUS" != "200" ]; then
  echo "Create raid failed body:"
  echo "$RESP" | jq . 2>/dev/null || echo "$RESP"
  die "Create raid did not return 200"
fi

RAID_ID=$(echo "$RESP" | jq -r '.raid_id // empty')
OUTBOUND=$(echo "$RESP" | jq -r '.outbound_seconds // empty')
RETURN=$(echo "$RESP" | jq -r '.return_seconds // empty')

# Validate fields exist and are integers
[[ "$RAID_ID" =~ ^[0-9]+$ ]] || die "Create raid response missing raid_id. Body: $(echo "$RESP" | jq -c .)"
[[ "$OUTBOUND" =~ ^[0-9]+$ ]] || die "Create raid response missing outbound_seconds. Body: $(echo "$RESP" | jq -c .)"
[[ "$RETURN" =~ ^[0-9]+$ ]] || die "Create raid response missing return_seconds. Body: $(echo "$RESP" | jq -c .)"

echo "raid_id=$RAID_ID outbound=$OUTBOUND return=$RETURN"

echo "== Wait for full round trip =="
sleep $((OUTBOUND + RETURN + 2))

echo "== Poll until resolved (tick-on-read is inside /raids/{id}) =="
STATUS=""
for i in {1..15}; do
  RAID_JSON=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" "$BASE/raids/$RAID_ID")
  STATUS=$(echo "$RAID_JSON" | jq -r .status)
  echo "status=$STATUS"
  if [ "$STATUS" = "resolved" ]; then
    break
  fi
  sleep 1
done

if [ "$STATUS" != "resolved" ]; then
  echo "Raid did not resolve. Last raid JSON:"
  echo "$RAID_JSON" | jq .
  die "Raid never resolved"
fi

echo "== Unread count after (should increase) =="
AFTER_JSON=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/unread_count?kind=raid_report")
AFTER=$(echo "$AFTER_JSON" | jq -r .unread)
echo "after=$AFTER"

if [ "$AFTER" -le "$BEFORE" ]; then
  echo "Inbox (top 5) for debugging:"
  curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
    "$BASE/mail/inbox?limit=5&kind=raid_report" | jq .
  die "Expected unread count to increase (before=$BEFORE after=$AFTER)"
fi

echo "== Get newest raid_report message and mark read =="
MSG_ID=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/inbox?limit=1&kind=raid_report" | jq -r '.messages[0].id')

[[ "$MSG_ID" =~ ^[0-9]+$ ]] || die "No message found to mark read"

echo "msg_id=$MSG_ID"
curl -sS -X POST -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/$MSG_ID/read" | jq '.ok'

echo "== Unread count after mark_read (should decrement by 1) =="
FINAL_JSON=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/unread_count?kind=raid_report")
FINAL=$(echo "$FINAL_JSON" | jq -r .unread)
echo "final=$FINAL"

EXPECTED=$((AFTER - 1))
if [ "$FINAL" -ne "$EXPECTED" ]; then
  die "Expected unread to decrement by 1 (after=$AFTER final=$FINAL)"
fi

echo "✅ Mail flow UI-test passed"
