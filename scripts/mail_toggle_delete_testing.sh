#!/usr/bin/env bash
set -euo pipefail

BASE="http://127.0.0.1:8000"
KIND="raid_report"
ATTACKER_CITY_ID=3
TARGET_CITY_ID=1

die() { echo "❌ $*" >&2; exit 1; }
ok() { echo "✅ $*"; }

login() {
  curl -sS -X POST "$BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username":"alicia","password":"ChangeMe123!"}' | jq -r .token
}

unread_count() {
  local token="$1"
  curl -sS -H "Authorization: Bearer $token" \
    "$BASE/mail/unread_count?kind=$KIND" | jq -r .unread
}

latest_msg_id() {
  local token="$1"
  curl -sS -H "Authorization: Bearer $token" \
    "$BASE/mail/inbox?limit=1&kind=$KIND" | jq -r '.messages[0].id // empty'
}

recall_active_raids() {
  local token="$1"
  local ids1 ids2 rid

  ids1=$(curl -sS -H "Authorization: Bearer $token" \
    "$BASE/raids?status=enroute&limit=200" | jq -r '.raids[].raid_id' || true)
  ids2=$(curl -sS -H "Authorization: Bearer $token" \
    "$BASE/raids?status=returning&limit=200" | jq -r '.raids[].raid_id' || true)

  for rid in $ids1 $ids2; do
    echo "recalling raid_id=$rid"
    curl -sS -X POST -H "Authorization: Bearer $token" \
      "$BASE/raids/$rid/recall" >/dev/null || true
  done
}

create_raid() {
  local token="$1"

  # capture body + status
  local bodyfile status body
  bodyfile=$(mktemp)
  status=$(
    curl -sS -o "$bodyfile" -w "%{http_code}" \
      -X POST "$BASE/raids" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "{\"attacker_city_id\":$ATTACKER_CITY_ID,\"target_city_id\":$TARGET_CITY_ID,\"troops\":[{\"code\":\"t1_inf\",\"count\":10},{\"code\":\"t1_rng\",\"count\":5}],\"travel_seconds\":1}"
  )
  body=$(cat "$bodyfile"); rm -f "$bodyfile"

  if [ "$status" != "200" ]; then
    echo "Create raid failed body:"
    echo "$body" | jq . 2>/dev/null || echo "$body"
    die "Create raid did not return 200 (status=$status)"
  fi

  echo "$body"
}

wait_for_resolved() {
  local token="$1"
  local raid_id="$2"

  local status=""
  for i in {1..20}; do
    status=$(curl -sS -H "Authorization: Bearer $token" \
      "$BASE/raids/$raid_id" | jq -r .status)
    echo "raid_status=$status"
    if [ "$status" = "resolved" ]; then
      return 0
    fi
    sleep 1
  done
  die "Raid never resolved (last status=$status)"
}

wait_for_unread_increase() {
  local token="$1"
  local before="$2"

  for i in {1..20}; do
    local now
    now=$(unread_count "$token")
    echo "unread_now=$now" >&2
    if [ "$now" -gt "$before" ]; then
      echo "$now"
      return 0
    fi
    sleep 1
  done

  echo "Inbox (top 5) for debugging:"
  curl -sS -H "Authorization: Bearer $token" \
    "$BASE/mail/inbox?limit=5&kind=$KIND" | jq .
  die "Expected unread to increase (before=$before)"
}

echo "== Login Alicia =="
TOKEN="$(login)"
[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "null" ] || die "Login failed (token empty/null)"

echo "== Cleanup: recall any active raids for attacker_city_id=$ATTACKER_CITY_ID =="
recall_active_raids "$TOKEN"

echo "== Unread before =="
BEFORE="$(unread_count "$TOKEN")"
echo "before=$BEFORE"

echo "== Create 1 short raid (travel_seconds=1) =="
RESP="$(create_raid "$TOKEN")"
RAID_ID="$(echo "$RESP" | jq -r '.raid_id')"
OUTBOUND="$(echo "$RESP" | jq -r '.outbound_seconds')"
RETURN="$(echo "$RESP" | jq -r '.return_seconds')"
echo "raid_id=$RAID_ID outbound=$OUTBOUND return=$RETURN"

echo "== Wait for full round trip =="
sleep $((OUTBOUND + RETURN + 2))

echo "== Poll until resolved =="
wait_for_resolved "$TOKEN" "$RAID_ID"

echo "== Confirm unread goes up (poll a bit) =="
AFTER="$(wait_for_unread_increase "$TOKEN" "$BEFORE")"
echo "after=$AFTER"

echo "== Get newest raid_report message id =="
MSG_ID="$(latest_msg_id "$TOKEN")"
[[ "$MSG_ID" =~ ^[0-9]+$ ]] || die "No message found in inbox"
echo "msg_id=$MSG_ID"

echo "== mark_read → confirm unread decrements =="
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  "$BASE/mail/$MSG_ID/read" | jq -e '.ok == true' >/dev/null || die "mark_read failed"

READ_COUNT="$(unread_count "$TOKEN")"
echo "unread_after_read=$READ_COUNT"
[ "$READ_COUNT" -eq $((AFTER - 1)) ] || die "Expected unread to decrement by 1 (after=$AFTER got=$READ_COUNT)"

echo "== mark_unread → confirm unread increments =="
curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  "$BASE/mail/$MSG_ID/unread" | jq -e '.ok == true' >/dev/null || die "mark_unread failed"

UNREAD_COUNT="$(unread_count "$TOKEN")"
echo "unread_after_unread=$UNREAD_COUNT"
[ "$UNREAD_COUNT" -eq "$AFTER" ] || die "Expected unread to return to $AFTER (got=$UNREAD_COUNT)"

echo "== delete → confirm 404 on read =="
curl -sS -X DELETE -H "Authorization: Bearer $TOKEN" \
  "$BASE/mail/$MSG_ID" | jq -e '.ok == true' >/dev/null || die "delete failed"

HTTP=$(curl -sS -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  "$BASE/mail/$MSG_ID")
[ "$HTTP" = "404" ] || die "Expected 404 after delete, got $HTTP"

ok "Mail toggle+delete UI-test passed"
