#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DB_PATH="${DB_PATH:-/home/mmcelwee/evony/data/game.db}"

# Defaults (override via env if you want)
USERNAME="${USERNAME:-alicia}"
PASSWORD="${PASSWORD:-ChangeMe123!}"
ATTACKER_CITY_ID="${ATTACKER_CITY_ID:-3}"
TARGET_CITY_ID="${TARGET_CITY_ID:-1}"
TRAVEL_SECONDS="${TRAVEL_SECONDS:-10}"

# Troops (Option B uses "code")
TROOPS_JSON='[{"code":"t1_inf","count":10},{"code":"t1_rng","count":5}]'

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing dependency: $1"; exit 1; }; }
need jq
need sqlite3
need curl

echo "== Login =="
TOKEN="$(curl -sS -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" | jq -r .token)"

if [[ -z "${TOKEN:-}" || "$TOKEN" == "null" ]]; then
  echo "Login failed (no token)."
  exit 1
fi

echo
echo "== Cleanup: recall any active raids for attacker_city_id=$ATTACKER_CITY_ID =="
RAIDS_JSON="$(curl -sS -H "Authorization: Bearer $TOKEN" "$BASE_URL/raids?limit=200")"

ACTIVE_IDS="$(echo "$RAIDS_JSON" | jq -r --argjson cid "$ATTACKER_CITY_ID" '
  .raids[]
  | select(.attacker_city_id == $cid)
  | select(.status == "enroute" or .status == "returning")
  | .raid_id
')"

if [[ -z "${ACTIVE_IDS:-}" ]]; then
  echo "No active raids found."
else
  echo "Found active raids: $(echo "$ACTIVE_IDS" | tr '\n' ' ')"
  while read -r rid; do
    [[ -z "$rid" ]] && continue
    echo "Recalling raid_id=$rid ..."
    curl -sS -X POST "$BASE_URL/raids/$rid/recall" \
      -H "Authorization: Bearer $TOKEN" >/dev/null || true
  done <<< "$ACTIVE_IDS"
  echo "Cleanup done."
fi

echo
echo "== Create raid =="
RESP="$(curl -sS -w $'\n%{http_code}' -X POST "$BASE_URL/raids" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"attacker_city_id\":$ATTACKER_CITY_ID,\"target_city_id\":$TARGET_CITY_ID,\"troops\":$TROOPS_JSON,\"travel_seconds\":$TRAVEL_SECONDS}")"

BODY="$(echo "$RESP" | sed '$d')"
CODE="$(echo "$RESP" | tail -n 1)"

echo "HTTP $CODE"
echo "$BODY" | jq .

if [[ "$CODE" != "200" ]]; then
  echo "Create raid failed."
  exit 1
fi

RAID_ID="$(echo "$BODY" | jq -r '.raid_id // empty')"
if [[ -z "${RAID_ID:-}" ]]; then
  echo "Create raid response missing raid_id."
  exit 1
fi
echo "RAID_ID=$RAID_ID"

echo
echo "== Wait for arrival (travel_seconds=$TRAVEL_SECONDS) =="
sleep $((TRAVEL_SECONDS + 2))

echo
echo "== Force tick-on-read + show raid status =="
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/raids/$RAID_ID" | jq '{raid_id,status,arrives_at,returns_at,resolved_at,stolen}'

echo
echo "== Wait for return + resolution =="
sleep $((TRAVEL_SECONDS + 2))
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/raids/$RAID_ID" | jq '{raid_id,status,arrives_at,returns_at,resolved_at}'

echo
echo "== Verify snapshot rows in raid_defender_troops (this raid) =="
sqlite3 "$DB_PATH" <<SQL
.headers on
.mode column
SELECT raid_id, troop_type_id, count_start, count_lost
FROM raid_defender_troops
WHERE raid_id = $RAID_ID
ORDER BY troop_type_id ASC;
SQL

echo
echo "== Fetch report (defender snapshot + totals) =="
curl -sS -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/raids/$RAID_ID/report" \
| jq '{
    raid_id: .raid.raid_id,
    status: .raid.status,
    defender_source: .defender.source,
    defender_totals: .defender.totals,
    defender_first: (.defender.troops[0] // null),
    attacker_totals: .attacker.totals
  }'

echo
echo "== Smoke test query (this raid only) =="
sqlite3 "$DB_PATH" \
"SELECT raid_id, troop_type_id, count_start, count_lost
 FROM raid_defender_troops
 WHERE raid_id = $RAID_ID
 ORDER BY raid_id DESC, troop_type_id ASC;"
echo
echo "✅ Smoke test complete for RAID_ID=$RAID_ID"
