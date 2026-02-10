#!/usr/bin/env bash
set -euo pipefail

DB_PATH="${DB_PATH:-/home/mmcelwee/evony/data/game.db}"
ATTACKER_CITY_ID="${ATTACKER_CITY_ID:-1}"
TARGET_CITY_ID="${TARGET_CITY_ID:-2}"

# Tune this to whatever makes testing comfortable
SET_FOOD="${SET_FOOD:-7000}"
SET_WOOD="${SET_WOOD:-7000}"
SET_STONE="${SET_STONE:-4200}"
SET_IRON="${SET_IRON:-2800}"

# Troops to ensure exist
ADD_T1_INF="${ADD_T1_INF:-500}"
ADD_T1_RNG="${ADD_T1_RNG:-300}"
ADD_T1_CAV="${ADD_T1_CAV:-200}"
ADD_T1_SIEGE="${ADD_T1_SIEGE:-50}"

sql() { sqlite3 "$DB_PATH" "$1"; }

echo "== Reset resources (and freeze production) =="
sql "
UPDATE cities
SET
  food=$SET_FOOD,
  wood=$SET_WOOD,
  stone=$SET_STONE,
  iron=$SET_IRON,
  last_tick_at=datetime('now')
WHERE id IN ($ATTACKER_CITY_ID,$TARGET_CITY_ID);
"

echo "== Ensure attacker troops exist =="
sql "
INSERT INTO city_troops (city_id, troop_type_id, count)
SELECT $ATTACKER_CITY_ID, id,
  CASE code
    WHEN 't1_inf' THEN $ADD_T1_INF
    WHEN 't1_rng' THEN $ADD_T1_RNG
    WHEN 't1_cav' THEN $ADD_T1_CAV
    WHEN 't1_siege' THEN $ADD_T1_SIEGE
    ELSE 0
  END
FROM troop_types
WHERE code IN ('t1_inf','t1_rng','t1_cav','t1_siege')
ON CONFLICT(city_id, troop_type_id) DO UPDATE SET count = excluded.count;
"

echo "== Ensure target troops exist (defender) =="
sql "
INSERT INTO city_troops (city_id, troop_type_id, count)
SELECT $TARGET_CITY_ID, id, 45
FROM troop_types
WHERE code IN ('t1_inf','t1_rng')
ON CONFLICT(city_id, troop_type_id) DO UPDATE SET count = excluded.count;
"

echo "== Clear raids between attacker and target =="
sql "
DELETE FROM raid_troops WHERE raid_id IN (
  SELECT id FROM raids WHERE attacker_city_id=$ATTACKER_CITY_ID AND target_city_id=$TARGET_CITY_ID
);
DELETE FROM raids WHERE attacker_city_id=$ATTACKER_CITY_ID AND target_city_id=$TARGET_CITY_ID;
"

echo "== Done. Snapshot =="
sql "
SELECT id, food, wood, stone, iron, last_tick_at
FROM cities WHERE id IN ($ATTACKER_CITY_ID,$TARGET_CITY_ID);
"
echo
sql "
SELECT ct.city_id, tt.code, ct.count
FROM city_troops ct
JOIN troop_types tt ON tt.id=ct.troop_type_id
WHERE ct.city_id IN ($ATTACKER_CITY_ID,$TARGET_CITY_ID)
ORDER BY ct.city_id, tt.id;
"
