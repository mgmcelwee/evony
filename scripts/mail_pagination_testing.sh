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
[ -n "${ALICIA_TOKEN:-}" ] && [ "$ALICIA_TOKEN" != "null" ] || die "Login failed"

unread() {
  curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
    "$BASE/mail/unread_count?kind=raid_report" | jq -r .unread
}

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

echo "== Unread before =="
BEFORE=$(unread)
echo "before=$BEFORE"

create_raid_and_wait_resolved() {
  local CREATE_BODY_FILE CREATE_STATUS RESP RAID_ID OUTBOUND RETURN STATUS RAID_JSON

  CREATE_BODY_FILE=$(mktemp)
  CREATE_STATUS=$(
    curl -sS -o "$CREATE_BODY_FILE" -w "%{http_code}" \
      -X POST "$BASE/raids" \
      -H "Authorization: Bearer $ALICIA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"attacker_city_id":3,"target_city_id":1,"travel_seconds":1,"troops":[{"code":"t1_inf","count":10},{"code":"t1_rng","count":5}]}'
  )
  RESP=$(cat "$CREATE_BODY_FILE"); rm -f "$CREATE_BODY_FILE"

  [ "$CREATE_STATUS" = "200" ] || { echo "$RESP" | jq . 2>/dev/null || echo "$RESP"; die "Create raid failed"; }

  RAID_ID=$(echo "$RESP" | jq -r '.raid_id // empty')
  OUTBOUND=$(echo "$RESP" | jq -r '.outbound_seconds // 1')
  RETURN=$(echo "$RESP" | jq -r '.return_seconds // 1')
  [[ "$RAID_ID" =~ ^[0-9]+$ ]] || die "Create raid missing raid_id"

  sleep $((OUTBOUND + RETURN + 2))

  STATUS=""
  for i in {1..15}; do
    RAID_JSON=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" "$BASE/raids/$RAID_ID")
    STATUS=$(echo "$RAID_JSON" | jq -r .status)
    if [ "$STATUS" = "resolved" ]; then break; fi
    sleep 1
  done
  [ "$STATUS" = "resolved" ] || die "Raid $RAID_ID did not resolve"
}

echo "== Create 3 raids (sequential) =="
create_raid_and_wait_resolved
create_raid_and_wait_resolved
create_raid_and_wait_resolved

echo "== Unread after creating 3 raids =="
AFTER=$(unread)
echo "after=$AFTER"
EXPECTED_MIN=$((BEFORE + 3))
[ "$AFTER" -ge "$EXPECTED_MIN" ] || die "Expected unread >= $EXPECTED_MIN (before=$BEFORE after=$AFTER)"

echo "== Page 1 (limit=2) =="
PAGE1=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/inbox?kind=raid_report&limit=2")
COUNT1=$(echo "$PAGE1" | jq -r '.count')
NEXT1=$(echo "$PAGE1" | jq -r '.next_before_id // empty')
echo "$PAGE1" | jq '{count, next_before_id, ids: [.messages[].id]}'

[ "$COUNT1" = "2" ] || die "Expected page1 count=2 got $COUNT1"
[[ "$NEXT1" =~ ^[0-9]+$ ]] || die "Expected next_before_id on page1"

echo "== Page 2 (before_id=$NEXT1, limit=2) =="
PAGE2=$(curl -sS -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/inbox?kind=raid_report&limit=2&before_id=$NEXT1")
COUNT2=$(echo "$PAGE2" | jq -r '.count')
echo "$PAGE2" | jq '{count, next_before_id, ids: [.messages[].id]}'
[ "$COUNT2" -ge "1" ] || die "Expected page2 count>=1 got $COUNT2"

echo "== Mark all raid_report as read =="
curl -sS -X POST -H "Authorization: Bearer $ALICIA_TOKEN" \
  "$BASE/mail/read_all?kind=raid_report" | jq .

echo "== Unread after read_all =="
FINAL=$(unread)
echo "final=$FINAL"
[ "$FINAL" = "0" ] || die "Expected unread=0 after read_all; got $FINAL"

echo "✅ Mail pagination + read_all UI-test passed"
