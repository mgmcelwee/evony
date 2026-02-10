#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------
# Config (override via env vars if you want)
# -----------------------------------------
DB_PATH="${DB_PATH:-/home/mmcelwee/evony/data/game.db}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

# IMPORTANT:
# - Script reads TOKEN from TOKEN or EVONY_TOKEN.
# - If you do: EVONY_TOKEN="..." ./script  -> works
# - If you do: EVONY_TOKEN="..."           -> does NOT export in bash
TOKEN="${TOKEN:-${EVONY_TOKEN:-}}"

ADMIN_KEY="${ADMIN_KEY:-${EVONY_ADMIN_KEY:-Mathew-evony-admin-9f3c7d2a11}}"

ATTACKER_CITY_ID="${ATTACKER_CITY_ID:-1}"
TARGET_CITY_ID="${TARGET_CITY_ID:-2}"

# Option B payload troops (override if you want)
TROOP1_CODE="${TROOP1_CODE:-t1_inf}"
TROOP1_COUNT="${TROOP1_COUNT:-50}"
TROOP2_CODE="${TROOP2_CODE:-t1_rng}"
TROOP2_COUNT="${TROOP2_COUNT:-25}"

# travel_seconds override for testing (supported by your create_raid)
TRAVEL_SECONDS="${TRAVEL_SECONDS:-10}"

# Optional: drain attacker so Stage 2 credit is visible (set to 0 to disable)
DRAIN_ATTACKER="${DRAIN_ATTACKER:-1}"
DRAIN_FOOD="${DRAIN_FOOD:-2000}"
DRAIN_WOOD="${DRAIN_WOOD:-2000}"
DRAIN_STONE="${DRAIN_STONE:-1200}"
DRAIN_IRON="${DRAIN_IRON:-800}"

# Wait buffers
ARRIVAL_SLEEP="${ARRIVAL_SLEEP:-12}"   # should be > TRAVEL_SECONDS
RETURN_SLEEP="${RETURN_SLEEP:-8}"      # should be > return_seconds

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: TOKEN env var is not set."
  echo "Fix:"
  echo "  export EVONY_TOKEN='...'"
  echo "  # or: EVONY_TOKEN='...' ./scripts/test_raid_tick.sh"
  exit 1
fi

echo "== Raid + Tick + Troops Test (Option B) =="
echo "DB_PATH=$DB_PATH"
echo "BASE_URL=$BASE_URL"
echo "ATTACKER_CITY_ID=$ATTACKER_CITY_ID"
echo "TARGET_CITY_ID=$TARGET_CITY_ID"
echo "TROOPS=$TROOP1_CODE:$TROOP1_COUNT, $TROOP2_CODE:$TROOP2_COUNT"
echo "TRAVEL_SECONDS=$TRAVEL_SECONDS"
echo

# -----------------------------
# Helpers
# -----------------------------
sql() { sqlite3 "$DB_PATH" "$1"; }

tick() {
  curl -sS -X POST "$BASE_URL/game/tick" \
    -H "Authorization: Bearer $TOKEN" \
    -H "X-Admin-Key: $ADMIN_KEY"
}

get_city_row() {
  local cid="$1"
  sql "SELECT id,food,wood,stone,iron,max_food,max_wood,max_stone,max_iron,
              protected_food,protected_wood,protected_stone,protected_iron,last_tick_at
       FROM cities WHERE id=$cid;"
}

get_city_resources_only() {
  local cid="$1"
  sql "SELECT food,wood,stone,iron FROM cities WHERE id=$cid;"
}

get_city_protected_compact() {
  local cid="$1"
  sql "SELECT protected_food,protected_wood,protected_stone,protected_iron
       FROM cities WHERE id=$cid;"
}

get_city_caps_compact() {
  local cid="$1"
  sql "SELECT max_food,max_wood,max_stone,max_iron FROM cities WHERE id=$cid;"
}

get_raid_loot_compact() {
  local rid="$1"
  sql "SELECT stolen_food,stolen_wood,stolen_stone,stolen_iron FROM raids WHERE id=$rid;"
}

get_raid_row() {
  local rid="$1"
  sql "SELECT id,status,outbound_seconds,return_seconds,carry_capacity,
              stolen_food,stolen_wood,stolen_stone,stolen_iron,
              created_at,arrives_at,returns_at,resolved_at
       FROM raids WHERE id=$rid;"
}

# City troops (code|count)
get_city_troops_compact() {
  local cid="$1"
  sql "
    SELECT tt.code, ct.count
    FROM city_troops ct
    JOIN troop_types tt ON tt.id = ct.troop_type_id
    WHERE ct.city_id = $cid
    ORDER BY tt.id;
  "
}

# Raid troops (code|sent|lost)
get_raid_troops_compact() {
  local rid="$1"
  sql "
    SELECT tt.code, rt.count_sent, rt.count_lost
    FROM raid_troops rt
    JOIN troop_types tt ON tt.id = rt.troop_type_id
    WHERE rt.raid_id = $rid
    ORDER BY tt.id;
  "
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if ! grep -q "$needle" <<<"$haystack"; then
    echo "ASSERT FAILED: expected output to contain: $needle"
    echo "---- output ----"
    echo "$haystack"
    echo "----------------"
    exit 1
  fi
}

drain_attacker() {
  local cid="$ATTACKER_CITY_ID"
  sql "
    UPDATE cities
    SET
      food  = MAX(0, food  - $DRAIN_FOOD),
      wood  = MAX(0, wood  - $DRAIN_WOOD),
      stone = MAX(0, stone - $DRAIN_STONE),
      iron  = MAX(0, iron  - $DRAIN_IRON)
    WHERE id=$cid;
  "
}

# Freeze production by syncing last_tick_at to now (for deterministic asserts)
sync_last_tick_now() {
  sql "UPDATE cities
       SET last_tick_at = datetime('now')
       WHERE id IN ($ATTACKER_CITY_ID, $TARGET_CITY_ID);"
}

# -----------------------------
# Snapshot BEFORE
# -----------------------------
echo "== City rows BEFORE =="
echo "Attacker:"
get_city_row "$ATTACKER_CITY_ID"
echo "Target:"
get_city_row "$TARGET_CITY_ID"
echo

echo "== City troops BEFORE =="
echo "Attacker troops:"
get_city_troops_compact "$ATTACKER_CITY_ID"
echo "Target troops:"
get_city_troops_compact "$TARGET_CITY_ID"
echo

# Freeze production immediately
sync_last_tick_now

# Optional drain attacker
if [[ "$DRAIN_ATTACKER" == "1" ]]; then
  echo "== Draining attacker so Stage 2 credit is visible =="
  drain_attacker
  echo "Attacker AFTER drain:"
  get_city_row "$ATTACKER_CITY_ID"
  echo
fi

# -----------------------------
# Clear old raids between these two cities
# -----------------------------
echo "== Clearing old raids between attacker/target =="
sql "DELETE FROM raid_troops WHERE raid_id IN (
        SELECT id FROM raids WHERE attacker_city_id=$ATTACKER_CITY_ID AND target_city_id=$TARGET_CITY_ID
     );"
sql "DELETE FROM raids WHERE attacker_city_id=$ATTACKER_CITY_ID AND target_city_id=$TARGET_CITY_ID;"
echo

# -----------------------------
# Create raid (Option B)
# -----------------------------
echo "== Creating raid (Option B troops payload) =="

ATTACKER_TROOPS_BEFORE_CREATE="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
export ATTACKER_TROOPS_BEFORE_CREATE TROOP1_CODE TROOP1_COUNT TROOP2_CODE TROOP2_COUNT

CREATE_PAYLOAD=$(
  cat <<JSON
{
  "attacker_city_id": $ATTACKER_CITY_ID,
  "target_city_id": $TARGET_CITY_ID,
  "travel_seconds": $TRAVEL_SECONDS,
  "troops": [
    {"code":"$TROOP1_CODE","count": $TROOP1_COUNT},
    {"code":"$TROOP2_CODE","count": $TROOP2_COUNT}
  ]
}
JSON
)

CREATE_RESP_WITH_CODE="$(
  curl -sS -X POST "$BASE_URL/raids" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CREATE_PAYLOAD" \
    -w $'\n%{http_code}'
)"

CREATE_BODY="$(echo "$CREATE_RESP_WITH_CODE" | sed '$d')"
CREATE_CODE="$(echo "$CREATE_RESP_WITH_CODE" | tail -n 1)"

echo "Create HTTP $CREATE_CODE"
echo "$CREATE_BODY" | jq . || echo "$CREATE_BODY"
echo

if [[ "$CREATE_CODE" != "200" && "$CREATE_CODE" != "201" ]]; then
  echo "ERROR: /raids failed (HTTP $CREATE_CODE). See body above."
  exit 1
fi

RID="$(echo "$CREATE_BODY" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("raid_id",""))')"
if [[ -z "$RID" ]]; then
  echo "ERROR: /raids succeeded but no raid_id found in response."
  exit 1
fi

echo "RID=$RID"
echo

echo "== Raid row right after create (expect enroute) =="
get_raid_row "$RID"
echo

echo "== Raid troops right after create (count_sent set) =="
get_raid_troops_compact "$RID"
echo

echo "== Attacker troops AFTER create (should be decremented by sent) =="
ATTACKER_TROOPS_AFTER_CREATE="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
echo "$ATTACKER_TROOPS_AFTER_CREATE"
echo
export ATTACKER_TROOPS_AFTER_CREATE

python3 - <<'PY'
import os

def parse_city(lines: str):
    m={}
    for ln in lines.splitlines():
        if not ln.strip():
            continue
        code, cnt = ln.split("|", 1)
        m[code.strip()] = int(cnt.strip())
    return m

b = parse_city(os.environ["ATTACKER_TROOPS_BEFORE_CREATE"])
a = parse_city(os.environ["ATTACKER_TROOPS_AFTER_CREATE"])

t1_code = os.environ["TROOP1_CODE"]
t1_cnt  = int(os.environ["TROOP1_COUNT"])
t2_code = os.environ["TROOP2_CODE"]
t2_cnt  = int(os.environ["TROOP2_COUNT"])

for code,n in [(t1_code,t1_cnt),(t2_code,t2_cnt)]:
    if code not in b or code not in a:
        raise SystemExit(f"ASSERT FAILED: missing troop code in city_troops: {code}")
    exp = b[code] - n
    if a[code] != exp:
        raise SystemExit(f"ASSERT FAILED: attacker {code} expected {exp}, got {a[code]}")
print("✅ Create raid reserved troops correctly (attacker city_troops decremented).")
PY

# -----------------------------
# Stage 1: wait past arrival and tick
# -----------------------------
echo "== Sleeping $ARRIVAL_SLEEP seconds (past arrives_at) =="
sleep "$ARRIVAL_SLEEP"
echo

sync_last_tick_now

TARGET_BEFORE_STAGE1="$(get_city_resources_only "$TARGET_CITY_ID")"
TARGET_PROTECTED="$(get_city_protected_compact "$TARGET_CITY_ID")"
TARGET_TROOPS_BEFORE_STAGE1="$(get_city_troops_compact "$TARGET_CITY_ID")"
export TARGET_BEFORE_STAGE1 TARGET_PROTECTED TARGET_TROOPS_BEFORE_STAGE1

echo "== Stage 1 tick (enroute -> returning, loot + casualties) =="
T1="$(tick)"
echo "$T1" | jq .
echo

echo "== Raid row after Stage 1 (expect returning + stolen_*) =="
RAID_AFTER_STAGE1="$(get_raid_row "$RID")"
echo "$RAID_AFTER_STAGE1"
echo
assert_contains "$RAID_AFTER_STAGE1" "|returning|"

echo "== Raid troops after Stage 1 (expect count_lost possibly >0) =="
RAID_TROOPS_AFTER_STAGE1="$(get_raid_troops_compact "$RID")"
echo "$RAID_TROOPS_AFTER_STAGE1"
echo
export RAID_TROOPS_AFTER_STAGE1

echo "== Target troops after Stage 1 (defender losses may reduce counts) =="
TARGET_TROOPS_AFTER_STAGE1="$(get_city_troops_compact "$TARGET_CITY_ID")"
echo "$TARGET_TROOPS_AFTER_STAGE1"
echo
export TARGET_TROOPS_AFTER_STAGE1

# Stage 1 resource assertion
LOOT_STAGE1="$(get_raid_loot_compact "$RID")"
TARGET_AFTER_STAGE1="$(get_city_resources_only "$TARGET_CITY_ID")"
export LOOT_STAGE1 TARGET_AFTER_STAGE1

python3 - <<'PY'
import os
before = list(map(int, os.environ["TARGET_BEFORE_STAGE1"].split("|")))
after  = list(map(int, os.environ["TARGET_AFTER_STAGE1"].split("|")))
loot   = list(map(int, os.environ["LOOT_STAGE1"].split("|")))
prot   = list(map(int, os.environ["TARGET_PROTECTED"].split("|")))

bf,bw,bs,bi = before
af,aw,aS,ai = after
lf,lw,ls,li = loot
pf,pw,ps,pi = prot

ef = max(pf, bf - lf)
ew = max(pw, bw - lw)
es = max(ps, bs - ls)
ei = max(pi, bi - li)

if (af,aw,aS,ai) != (ef,ew,es,ei):
    raise SystemExit("ASSERT FAILED: target resources after Stage 1 != expected (before - loot, floored at protected)")
print("✅ Stage 1 resource decrease matches loot (floored at protected).")
PY

python3 - <<'PY'
import os

def parse_raid(lines: str):
    m={}
    for ln in lines.splitlines():
        if not ln.strip():
            continue
        code,sent,lost = ln.split("|")
        m[code]= (int(sent), int(lost))
    return m

def parse_city(lines: str):
    m={}
    for ln in lines.splitlines():
        if not ln.strip():
            continue
        code,cnt = ln.split("|")
        m[code]= int(cnt)
    return m

raid = parse_raid(os.environ.get("RAID_TROOPS_AFTER_STAGE1",""))
before = parse_city(os.environ.get("TARGET_TROOPS_BEFORE_STAGE1",""))
after = parse_city(os.environ.get("TARGET_TROOPS_AFTER_STAGE1",""))

atk_lost_total = sum(lost for _,(_,lost) in raid.items())
def_lost_total = sum(max(0, before.get(code,0) - after.get(code,0)) for code in before.keys())

print("== Casualty sanity check ==")
print("Attacker losses total:", atk_lost_total)
print("Defender losses total:", def_lost_total)

if atk_lost_total == 0 and def_lost_total == 0:
    print("⚠️  WARNING: No casualties recorded. If you expect some, tweak your casualty rates.")
else:
    print("✅ Casualties recorded (attacker and/or defender).")
PY

# -----------------------------
# Stage 2: wait past return and tick
# -----------------------------
echo "== Sleeping $RETURN_SLEEP seconds (past returns_at) =="
sleep "$RETURN_SLEEP"
echo

sync_last_tick_now

ATTACKER_RES_BEFORE_STAGE2="$(get_city_resources_only "$ATTACKER_CITY_ID")"
ATTACKER_CAPS="$(get_city_caps_compact "$ATTACKER_CITY_ID")"
ATTACKER_TROOPS_BEFORE_STAGE2="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
LOOT_STAGE2="$(get_raid_loot_compact "$RID")"
RAID_TROOPS_BEFORE_STAGE2="$(get_raid_troops_compact "$RID")"
export ATTACKER_RES_BEFORE_STAGE2 ATTACKER_CAPS ATTACKER_TROOPS_BEFORE_STAGE2 LOOT_STAGE2 RAID_TROOPS_BEFORE_STAGE2

echo "== Stage 2 tick (returning -> resolved, credit + return troops) =="
T2="$(tick)"
echo "$T2" | jq .
echo

echo "== Raid row after Stage 2 (expect resolved) =="
RAID_AFTER_STAGE2="$(get_raid_row "$RID")"
echo "$RAID_AFTER_STAGE2"
echo
assert_contains "$RAID_AFTER_STAGE2" "|resolved|"

ATTACKER_RES_AFTER_STAGE2="$(get_city_resources_only "$ATTACKER_CITY_ID")"
ATTACKER_TROOPS_AFTER_STAGE2="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
export ATTACKER_RES_AFTER_STAGE2 ATTACKER_TROOPS_AFTER_STAGE2

echo "== Attacker resources AFTER Stage 2 =="
echo "$ATTACKER_RES_AFTER_STAGE2"
echo
echo "== Attacker troops AFTER Stage 2 =="
echo "$ATTACKER_TROOPS_AFTER_STAGE2"
echo

python3 - <<'PY'
import os

before = list(map(int, os.environ["ATTACKER_RES_BEFORE_STAGE2"].split("|")))
after  = list(map(int, os.environ["ATTACKER_RES_AFTER_STAGE2"].split("|")))
caps   = list(map(int, os.environ["ATTACKER_CAPS"].split("|")))
loot   = list(map(int, os.environ["LOOT_STAGE2"].split("|")))

bf,bw,bs,bi = before
af,aw,aS,ai = after
mf,mw,ms,mi = caps
lf,lw,ls,li = loot

ef = min(mf, bf + lf)
ew = min(mw, bw + lw)
es = min(ms, bs + ls)
ei = min(mi, bi + li)

if (af,aw,aS,ai) != (ef,ew,es,ei):
    raise SystemExit("ASSERT FAILED: attacker resources after Stage 2 != expected (loot + caps)")
print("✅ Stage 2 loot credit matches expected (+ caps).")
PY

python3 - <<'PY'
import os

def parse_city(lines: str):
    m={}
    for ln in lines.splitlines():
        if not ln.strip(): continue
        code,cnt = ln.split("|")
        m[code]= int(cnt)
    return m

def parse_raid(lines: str):
    m={}
    for ln in lines.splitlines():
        if not ln.strip(): continue
        code,sent,lost = ln.split("|")
        m[code]= (int(sent), int(lost))
    return m

city_b = parse_city(os.environ["ATTACKER_TROOPS_BEFORE_STAGE2"])
city_a = parse_city(os.environ["ATTACKER_TROOPS_AFTER_STAGE2"])
raid   = parse_raid(os.environ["RAID_TROOPS_BEFORE_STAGE2"])

for code,(sent,lost) in raid.items():
    returning = max(0, sent - lost)
    if code not in city_b or code not in city_a:
        raise SystemExit(f"ASSERT FAILED: troop code missing in city troops: {code}")
    exp = city_b[code] + returning
    if city_a[code] != exp:
        raise SystemExit(f"ASSERT FAILED: {code} expected {exp} after return, got {city_a[code]} (returning={returning})")

print("✅ Stage 2 troop return matches (sent - lost) per troop type.")
PY

# -----------------------------
# Idempotency: run tick again (should NOT return troops twice)
# -----------------------------
echo "== Idempotency test: run tick again (troops should NOT change) =="
sync_last_tick_now

ATTACKER_TROOPS_BEFORE_IDEMP="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
export ATTACKER_TROOPS_BEFORE_IDEMP

T3="$(tick)"
echo "$T3" | jq .
echo

ATTACKER_TROOPS_AFTER_IDEMP="$(get_city_troops_compact "$ATTACKER_CITY_ID")"
export ATTACKER_TROOPS_AFTER_IDEMP

python3 - <<'PY'
import os
b = os.environ["ATTACKER_TROOPS_BEFORE_IDEMP"].strip()
a = os.environ["ATTACKER_TROOPS_AFTER_IDEMP"].strip()
if a != b:
    raise SystemExit("ASSERT FAILED: troops changed on idempotency re-run (should not).")
print("✅ Idempotency OK: troops did not return twice.")
PY

echo
echo "✅ Done. Raid $RID progressed: enroute -> returning -> resolved, loot+casualties+troop returns validated."
