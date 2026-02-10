#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# Config (override via env vars)
# -----------------------------
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
DB_PATH="${DB_PATH:-/home/mmcelwee/evony/data/game.db}"
ADMIN_KEY="${ADMIN_KEY:-Mathew-evony-admin-9f3c7d2a11}"

ALICIA_USER="${ALICIA_USER:-alicia}"
ALICIA_PASS="${ALICIA_PASS:-ChangeMe123!}"
MATHEW_USER="${MATHEW_USER:-mathew}"
MATHEW_PASS="${MATHEW_PASS:-ChangeMe123!}"

ALICIA_CITY_ID="${ALICIA_CITY_ID:-3}"
TARGET_CITY_ID="${TARGET_CITY_ID:-1}"

# Default raid payload (scenarios can override travel_seconds)
TRAVEL_SECONDS="${TRAVEL_SECONDS:-10}"
TROOP1_CODE="${TROOP1_CODE:-t1_inf}"
TROOP1_COUNT="${TROOP1_COUNT:-10}"
TROOP2_CODE="${TROOP2_CODE:-t1_rng}"
TROOP2_COUNT="${TROOP2_COUNT:-5}"

SEED_INF="${SEED_INF:-100}"
SEED_RNG="${SEED_RNG:-60}"

# Auto-handle 409 retry behavior
# CREATE_MAX_ATTEMPTS = total attempts
CREATE_MAX_ATTEMPTS="${CREATE_MAX_ATTEMPTS:-3}"
# CREATE_RETRY_SLEEP_BASE = seconds; grows per attempt
CREATE_RETRY_SLEEP_BASE="${CREATE_RETRY_SLEEP_BASE:-2}"

# Scenario timings (override if you want)
# SCEN_A_SLEEP = seconds after create before recall
SCEN_A_SLEEP="${SCEN_A_SLEEP:-1}"
# SCEN_B_EXTRA = seconds after arrives_at (travel) before recall
SCEN_B_EXTRA="${SCEN_B_EXTRA:-1}"
# SCEN_C_EXTRA = seconds after arrives_at (travel) before "ensure returning"
SCEN_C_EXTRA="${SCEN_C_EXTRA:-1}"
# SCEN_C_BETWEEN = seconds between "before" and recall to measure speedup
SCEN_C_BETWEEN="${SCEN_C_BETWEEN:-1}"

# -----------------------------
# Helpers
# -----------------------------
log() { echo "$*" >&2; }
die() { echo "ERROR: $*" >&2; exit 1; }
pretty_json() { python3 -m json.tool; }

# curl wrapper that returns: <body>\n<http_code>
curl_body_code() { curl -sS "$@" -w $'\n%{http_code}'; }

# Print status + pretty JSON (to stdout; used for human display, NOT capture)
http_json() {
  local method="$1"; shift
  local url="$1"; shift

  local resp body code
  resp="$(curl_body_code -X "$method" "$url" "$@")"
  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"

  echo "HTTP $code"
  if [[ -n "${body// }" ]]; then
    echo "$body" | pretty_json 2>/dev/null || echo "$body"
  else
    echo "(empty body)"
  fi
}

login_token() {
  local user="$1"
  local pass="$2"

  local resp body code token
  resp="$(curl_body_code -X POST "$BASE_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$user\",\"password\":\"$pass\"}")"

  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"

  if [[ "$code" != "200" ]]; then
    log "== /auth/login failed for user=$user (HTTP $code) =="
    [[ -n "${body// }" ]] && (echo "$body" | pretty_json >&2 2>/dev/null || echo "$body" >&2)
    die "Login failed for $user"
  fi

  [[ -n "${body// }" ]] || die "/auth/login returned empty body for $user"

  token="$(python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("token",""))' <<<"$body")"
  [[ -n "${token// }" ]] || die "Login JSON missing token for $user"
  echo "$token"
}

seed_alicia_troops() {
  log "== Seeding Alicia troops in DB (city_id=$ALICIA_CITY_ID) =="

  sqlite3 "$DB_PATH" <<SQL
INSERT INTO city_troops (city_id, troop_type_id, count)
SELECT $ALICIA_CITY_ID, id, $SEED_INF
FROM troop_types
WHERE code='$TROOP1_CODE'
  AND NOT EXISTS (
    SELECT 1 FROM city_troops ct
    WHERE ct.city_id=$ALICIA_CITY_ID
      AND ct.troop_type_id=(SELECT id FROM troop_types WHERE code='$TROOP1_CODE')
  );

UPDATE city_troops
SET count = $SEED_INF
WHERE city_id=$ALICIA_CITY_ID
  AND troop_type_id = (SELECT id FROM troop_types WHERE code='$TROOP1_CODE');

INSERT INTO city_troops (city_id, troop_type_id, count)
SELECT $ALICIA_CITY_ID, id, $SEED_RNG
FROM troop_types
WHERE code='$TROOP2_CODE'
  AND NOT EXISTS (
    SELECT 1 FROM city_troops ct
    WHERE ct.city_id=$ALICIA_CITY_ID
      AND ct.troop_type_id=(SELECT id FROM troop_types WHERE code='$TROOP2_CODE')
  );

UPDATE city_troops
SET count = $SEED_RNG
WHERE city_id=$ALICIA_CITY_ID
  AND troop_type_id = (SELECT id FROM troop_types WHERE code='$TROOP2_CODE');
SQL

  log "Alicia city_troops now:"
  sqlite3 "$DB_PATH" "SELECT tt.code, ct.count
    FROM city_troops ct
    JOIN troop_types tt ON tt.id=ct.troop_type_id
    WHERE ct.city_id=$ALICIA_CITY_ID
    ORDER BY tt.id;" >&2
  log ""
}

admin_list_raids_json() {
  local resp body code
  resp="$(curl_body_code -X GET "$BASE_URL/raids?limit=500" \
    -H "Authorization: Bearer $MATHEW_TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY")"

  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"

  log "Admin list raids: HTTP $code"
  [[ "$code" == "200" ]] || {
    [[ -n "${body// }" ]] && (echo "$body" | pretty_json >&2 2>/dev/null || echo "$body" >&2)
    die "Admin list raids failed (HTTP $code)"
  }
  echo "$body"
}

nudge_ticks() {
  curl -sS -X GET "$BASE_URL/raids?limit=1" \
    -H "Authorization: Bearer $MATHEW_TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY" >/dev/null 2>&1 || true
}

cleanup_alicia_active_raids() {
  log "== Cleanup: recalling any active raids for Alicia city_id=$ALICIA_CITY_ID =="

  local body raid_ids
  body="$(admin_list_raids_json)"

  if ! python3 -c 'import sys,json; json.load(sys.stdin)' <<<"$body" >/dev/null 2>&1; then
    log "ERROR: /raids returned non-JSON. First 300 chars:"
    log "${body:0:300}"
    die "Admin list raids returned non-JSON"
  fi

  raid_ids="$(python3 -c '
import sys,json
alicia_city_id = int(sys.argv[1])
j=json.load(sys.stdin)
out=[]
for r in j.get("raids", []):
    if r.get("attacker_city_id")==alicia_city_id and r.get("status")!="resolved":
        out.append(str(r.get("raid_id")))
print("\n".join(out))
' "$ALICIA_CITY_ID" <<<"$body")"

  if [[ -z "${raid_ids// }" ]]; then
    log "No active Alicia raids found."
    log ""
    return 0
  fi

  log "Found active Alicia raids:"
  echo "$raid_ids" | sed 's/^/  - /' >&2
  log ""

  while IFS= read -r rid; do
    [[ -n "$rid" ]] || continue
    log "Recalling raid_id=$rid ..."
    http_json POST "$BASE_URL/raids/$rid/recall" \
      -H "Authorization: Bearer $MATHEW_TOKEN" \
      -H "X-Admin-Key: $ADMIN_KEY" >/dev/null || true
  done <<<"$raid_ids"

  for _ in 1 2 3 4 5; do
    sleep 1
    nudge_ticks
  done

  log "Cleanup complete."
  log ""
}

create_raid_as_alicia() {
  local travel_seconds="${1:-$TRAVEL_SECONDS}"
  local attempt=1 raid_id=""

  while (( attempt <= CREATE_MAX_ATTEMPTS )); do
    local payload resp body code

    payload="$(cat <<JSON
{
  "attacker_city_id": $ALICIA_CITY_ID,
  "target_city_id": $TARGET_CITY_ID,
  "travel_seconds": $travel_seconds,
  "troops": [
    {"code":"$TROOP1_CODE","count": $TROOP1_COUNT},
    {"code":"$TROOP2_CODE","count": $TROOP2_COUNT}
  ]
}
JSON
)"

    log "== Creating raid as Alicia (attempt $attempt/$CREATE_MAX_ATTEMPTS, travel_seconds=$travel_seconds) =="
    resp="$(curl_body_code -X POST "$BASE_URL/raids" \
      -H "Authorization: Bearer $ALICIA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "$payload")"

    body="$(echo "$resp" | sed '$d')"
    code="$(echo "$resp" | tail -n 1)"

    log "HTTP $code"
    if [[ -n "${body// }" ]]; then
      echo "$body" | pretty_json >&2 2>/dev/null || echo "$body" >&2
    else
      log "(empty body)"
    fi

    if [[ "$code" == "200" ]]; then
      raid_id="$(python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("raid_id",""))' <<<"$body")"
      [[ -n "${raid_id// }" ]] || die "Create raid response missing raid_id"
      echo "$raid_id"
      return 0
    fi

    if [[ "$code" == "409" ]]; then
      log "Create raid returned 409. Auto-handling: cleanup Alicia active raids, nudge ticks, retry..."
      cleanup_alicia_active_raids
      nudge_ticks

      local sleep_s=$(( CREATE_RETRY_SLEEP_BASE * attempt ))
      log "Sleeping ${sleep_s}s before retry..."
      sleep "$sleep_s"

      ((attempt++))
      continue
    fi

    die "Create raid failed (HTTP $code)"
  done

  die "Create raid still failing after $CREATE_MAX_ATTEMPTS attempts."
}

assert_admin_can_access_raid() {
  local rid="$1"

  local resp body code
  resp="$(curl_body_code -X GET "$BASE_URL/raids/$rid" \
    -H "Authorization: Bearer $MATHEW_TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY")"

  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"

  if [[ "$code" != "200" ]]; then
    log ""
    log "❌ Admin sanity check failed: GET /raids/$rid with X-Admin-Key returned HTTP $code"
    log "Most common fix: start the server with the same ADMIN_KEY:"
    log "  export ADMIN_KEY=\"$ADMIN_KEY\""
    log "  ./scripts/run_server.sh"
    log ""
    log "Response body:"
    [[ -n "${body// }" ]] && (echo "$body" | pretty_json >&2 2>/dev/null || echo "$body" >&2) || log "(empty body)"
    die "Admin override rejected by server"
  fi
}

get_raid_admin_json() {
  local rid="$1"
  local resp body code
  resp="$(curl_body_code -X GET "$BASE_URL/raids/$rid" \
    -H "Authorization: Bearer $MATHEW_TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY")"
  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"
  [[ "$code" == "200" ]] || die "GET /raids/$rid as admin failed HTTP $code"
  echo "$body"
}

recall_raid_admin_json() {
  local rid="$1"
  local resp body code
  resp="$(curl_body_code -X POST "$BASE_URL/raids/$rid/recall" \
    -H "Authorization: Bearer $MATHEW_TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY")"
  body="$(echo "$resp" | sed '$d')"
  code="$(echo "$resp" | tail -n 1)"
  [[ "$code" == "200" ]] || die "POST /raids/$rid/recall as admin failed HTTP $code"
  echo "$body"
}

assert_eq() {
  local got="$1" want="$2" msg="${3:-}"
  [[ "$got" == "$want" ]] || die "ASSERT FAILED: expected [$want] got [$got] ${msg}"
}

assert_int_lt() {
  local a="$1" b="$2" msg="${3:-}"
  python3 -c 'import sys; a=int(sys.argv[1]); b=int(sys.argv[2]); sys.exit(0 if a < b else 1)' \
    "$a" "$b" || die "ASSERT FAILED: expected $a < $b ${msg}"
}

assert_stolen_all_zero() {
  local json="$1"
  local sum
  sum="$(python3 -c '
import sys,json
j=json.load(sys.stdin)
s=j.get("stolen", {}) or {}
total = int(s.get("food",0) or 0)+int(s.get("wood",0) or 0)+int(s.get("stone",0) or 0)+int(s.get("iron",0) or 0)
print(total)
' <<<"$json")"
  [[ "$sum" == "0" ]] || die "ASSERT FAILED: expected stolen sum 0, got $sum"
}

get_time_remaining() {
  local json="$1"
  python3 -c '
import sys,json
j=json.load(sys.stdin)
v=j.get("time_remaining_seconds")
if v is None: v=0
print(int(v))
' <<<"$json"
}

get_status() {
  local json="$1"
  python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("status",""))' <<<"$json"
}

scenario_a_recall_early() {
  local travel="$1"
  log "-----------------------------"
  log "Scenario A: recall immediately (enroute, before arrival)"
  log "-----------------------------"

  cleanup_alicia_active_raids
  local rid
  rid="$(create_raid_as_alicia "$travel")"
  echo "SCENARIO_A_RAID_ID=$rid"
  assert_admin_can_access_raid "$rid"

  sleep "$SCEN_A_SLEEP"

  local recall_json
  recall_json="$(recall_raid_admin_json "$rid")"
  echo "$recall_json" | pretty_json 2>/dev/null || echo "$recall_json"

  local st
  st="$(get_status "$recall_json")"
  assert_eq "$st" "returning" "(Scenario A status)"
  assert_stolen_all_zero "$recall_json"
}

scenario_b_recall_after_arrival() {
  local travel="$1"
  log "-----------------------------"
  log "Scenario B: recall after arrival (now >= arrives_at)"
  log "-----------------------------"

  cleanup_alicia_active_raids
  local rid
  rid="$(create_raid_as_alicia "$travel")"
  echo "SCENARIO_B_RAID_ID=$rid"
  assert_admin_can_access_raid "$rid"

  sleep $(( travel + SCEN_B_EXTRA ))

  local recall_json
  recall_json="$(recall_raid_admin_json "$rid")"
  echo "$recall_json" | pretty_json 2>/dev/null || echo "$recall_json"

  local st
  st="$(get_status "$recall_json")"
  assert_eq "$st" "returning" "(Scenario B status)"
}

scenario_c_recall_speeds_up_return() {
  local travel="$1"
  log "-----------------------------"
  log "Scenario C: recall while returning speeds up remaining time (GET/POST/GET proof)"
  log "-----------------------------"

  cleanup_alicia_active_raids
  local rid
  rid="$(create_raid_as_alicia "$travel")"
  echo "SCENARIO_C_RAID_ID=$rid"
  assert_admin_can_access_raid "$rid"

  # push it past arrival so tick-on-read will put it into returning
  sleep $(( travel + SCEN_C_EXTRA ))

  # Wait until the raid is actually returning (up to ~10s)
  local before_json before_status before_remaining
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    before_json="$(get_raid_admin_json "$rid")"
    before_status="$(get_status "$before_json")"
    before_remaining="$(get_time_remaining "$before_json")"
    if [[ "$before_status" == "returning" ]]; then
      break
    fi
    nudge_ticks
    sleep 1
  done

  log "Before recall: status=$before_status remaining=$before_remaining"
  [[ "$before_status" == "returning" ]] || die "Scenario C precondition failed: raid not returning"

  # small delay so we have a meaningful remaining window
  sleep "$SCEN_C_BETWEEN"

  # Recall
  local recall_json
  recall_json="$(recall_raid_admin_json "$rid")"
  echo "$recall_json" | pretty_json 2>/dev/null || echo "$recall_json"

  # GET again after recall to prove persisted effect
  local after_json after_status after_remaining
  after_json="$(get_raid_admin_json "$rid")"
  after_status="$(get_status "$after_json")"
  after_remaining="$(get_time_remaining "$after_json")"

  log "After recall (GET): status=$after_status remaining=$after_remaining"
  [[ "$after_status" == "returning" ]] || die "Scenario C postcondition failed: expected returning after recall"

  if (( before_remaining >= 2 )); then
    assert_int_lt "$after_remaining" "$before_remaining" "(Scenario C remaining should shrink)"
  else
    log "Skipping strict remaining assertion because before_remaining was too small ($before_remaining)."
  fi
}

echo "BASE_URL=$BASE_URL"
echo "DB_PATH=$DB_PATH"
echo "ALICIA_CITY_ID=$ALICIA_CITY_ID  TARGET_CITY_ID=$TARGET_CITY_ID"
echo

echo "== Login tokens =="
ALICIA_TOKEN="$(login_token "$ALICIA_USER" "$ALICIA_PASS")"
MATHEW_TOKEN="$(login_token "$MATHEW_USER" "$MATHEW_PASS")"
echo "ALICIA_TOKEN=${ALICIA_TOKEN:0:10}..."
echo "MATHEW_TOKEN=${MATHEW_TOKEN:0:10}..."
echo

seed_alicia_troops
cleanup_alicia_active_raids

BASE_RAID_ID="$(create_raid_as_alicia "$TRAVEL_SECONDS")"
echo "BASE_RAID_ID=$BASE_RAID_ID"
echo

assert_admin_can_access_raid "$BASE_RAID_ID"

echo "== Mathew GET /raids/$BASE_RAID_ID WITHOUT X-Admin-Key (expect 404) =="
http_json GET "$BASE_URL/raids/$BASE_RAID_ID" \
  -H "Authorization: Bearer $MATHEW_TOKEN"
echo

echo "== Mathew GET /raids/$BASE_RAID_ID WITH X-Admin-Key (expect 200) =="
http_json GET "$BASE_URL/raids/$BASE_RAID_ID" \
  -H "Authorization: Bearer $MATHEW_TOKEN" \
  -H "X-Admin-Key: $ADMIN_KEY"
echo

echo "== Mathew POST /raids/$BASE_RAID_ID/recall WITHOUT X-Admin-Key (expect 404) =="
http_json POST "$BASE_URL/raids/$BASE_RAID_ID/recall" \
  -H "Authorization: Bearer $MATHEW_TOKEN"
echo

echo "== Mathew POST /raids/$BASE_RAID_ID/recall WITH X-Admin-Key (expect 200) =="
http_json POST "$BASE_URL/raids/$BASE_RAID_ID/recall" \
  -H "Authorization: Bearer $MATHEW_TOKEN" \
  -H "X-Admin-Key: $ADMIN_KEY"
echo

SCEN_TRAVEL="${SCEN_TRAVEL:-6}"
scenario_a_recall_early "$SCEN_TRAVEL"
scenario_b_recall_after_arrival "$SCEN_TRAVEL"
scenario_c_recall_speeds_up_return "$SCEN_TRAVEL"

echo
echo "✅ All admin-override + recall scenario tests passed."
