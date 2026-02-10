# app/game/tick.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.game.raid_mail import send_raid_result_mail
from app.models.building import Building
from app.models.city import City
from app.models.raid import Raid
from app.models.upgrade import Upgrade
from app.models.city_troop import CityTroop
from app.models.raid_troop import RaidTroop
from app.models.troop_type import TroopType
from app.models.raid_defender_troop import RaidDefenderTroop

# ----------------------------
# Helpers: Rates + Storage
# ----------------------------

def _recalc_rates_for_city(db: Session, city_id: int) -> Dict[str, int]:
    buildings = db.query(Building).filter(Building.city_id == city_id).all()
    levels = {b.type: b.level for b in buildings}

    farm_lvl = levels.get("farm", 1)
    saw_lvl = levels.get("sawmill", 1)
    quarry_lvl = levels.get("quarry", 1)
    iron_lvl = levels.get("ironmine", 1)

    # Age 1 tuning:
    # - Early levels: small bumps
    # - Mid levels: economy starts to accelerate
    # - Keep it deterministic and easy to tweak
    #
    # Formula: base + linear*(lvl-1) + quadratic_bonus*(lvl-1)^2
    def curve(base: int, linear: int, quad: int, lvl: int) -> int:
        x = max(0, lvl - 1)
        return base + linear * x + quad * (x * x)

    food_rate = curve(base=30, linear=8, quad=2, lvl=farm_lvl)
    wood_rate = curve(base=30, linear=8, quad=2, lvl=saw_lvl)

    # Stone/iron remain slower in Age 1, but still benefit from upgrades
    stone_rate = curve(base=20, linear=3, quad=1, lvl=quarry_lvl)
    iron_rate = curve(base=10, linear=2, quad=1, lvl=iron_lvl)

    return {
        "food_rate": max(0, int(food_rate)),
        "wood_rate": max(0, int(wood_rate)),
        "stone_rate": max(0, int(stone_rate)),
        "iron_rate": max(0, int(iron_rate)),
    }

def _recalc_storage_for_city(db: Session, city_id: int) -> Dict[str, int]:
    buildings = db.query(Building).filter(Building.city_id == city_id).all()
    levels = {b.type: b.level for b in buildings}

    wh_lvl = levels.get("warehouse", 1)

    max_food = 5000 + wh_lvl * 2000
    max_wood = 5000 + wh_lvl * 2000
    max_stone = 3000 + wh_lvl * 1200
    max_iron = 2000 + wh_lvl * 800

    ratio = 0.25 + (wh_lvl - 1) * 0.02   # +2% per warehouse level after 1
    ratio = min(0.40, max(0.25, ratio))  # clamp 25%..40%

    protected_food = int(max_food * ratio)
    protected_wood = int(max_wood * ratio)
    protected_stone = int(max_stone * ratio)
    protected_iron = int(max_iron * ratio)

    return {
        "max_food": int(max_food),
        "max_wood": int(max_wood),
        "max_stone": int(max_stone),
        "max_iron": int(max_iron),
        "protected_food": int(protected_food),
        "protected_wood": int(protected_wood),
        "protected_stone": int(protected_stone),
        "protected_iron": int(protected_iron),
    }


# ----------------------------
# Tick: City production
# ----------------------------

def apply_city_tick(city: City, now: datetime, db: Session) -> int:
    last = city.last_tick_at or now
    minutes = int((now - last).total_seconds() // 60)
    if minutes <= 0:
        return 0

    rates = _recalc_rates_for_city(db, city.id)
    city.food_rate = rates["food_rate"]
    city.wood_rate = rates["wood_rate"]
    city.stone_rate = rates["stone_rate"]
    city.iron_rate = rates["iron_rate"]

    storage = _recalc_storage_for_city(db, city.id)
    city.max_food = storage["max_food"]
    city.max_wood = storage["max_wood"]
    city.max_stone = storage["max_stone"]
    city.max_iron = storage["max_iron"]
    city.protected_food = storage["protected_food"]
    city.protected_wood = storage["protected_wood"]
    city.protected_stone = storage["protected_stone"]
    city.protected_iron = storage["protected_iron"]

    city.food += city.food_rate * minutes
    city.wood += city.wood_rate * minutes
    city.stone += city.stone_rate * minutes
    city.iron += city.iron_rate * minutes

    city.food = min(city.food, city.max_food)
    city.wood = min(city.wood, city.max_wood)
    city.stone = min(city.stone, city.max_stone)
    city.iron = min(city.iron, city.max_iron)

    city.last_tick_at = last + timedelta(minutes=minutes)
    return minutes


# ----------------------------
# Raids: helpers
# ----------------------------

def _lootable(city: City) -> Dict[str, int]:
    return {
        "food": max(0, city.food - city.protected_food),
        "wood": max(0, city.wood - city.protected_wood),
        "stone": max(0, city.stone - city.protected_stone),
        "iron": max(0, city.iron - city.protected_iron),
    }


def _proportional_take(loot: Dict[str, int], capacity: int) -> Dict[str, int]:
    total = loot["food"] + loot["wood"] + loot["stone"] + loot["iron"]
    if total <= 0 or capacity <= 0:
        return {"food": 0, "wood": 0, "stone": 0, "iron": 0}

    take_total = min(capacity, total)

    taken: Dict[str, int] = {}
    remainders = []
    for k in ("food", "wood", "stone", "iron"):
        exact = (loot[k] / total) * take_total
        base = int(exact)
        base = min(base, loot[k])
        taken[k] = base
        remainders.append((exact - base, k))

    used = sum(taken.values())
    left = take_total - used
    remainders.sort(reverse=True)

    while left > 0:
        progressed = False
        for _, k in remainders:
            if left <= 0:
                break
            if taken[k] < loot[k]:
                taken[k] += 1
                left -= 1
                progressed = True
        if not progressed:
            break

    return taken

def _return_troops_from_raid(db: Session, raid: Raid) -> None:
    """
    When a raid resolves, return (count_sent - count_lost) to attacker city_troops.

    Idempotency guard:
    - After returning, set count_sent = count_lost (so returning becomes 0 on re-run).
      This prevents double returns if the server crashes mid-tick.
    """
    lines = (
        db.query(RaidTroop)
        .filter(RaidTroop.raid_id == raid.id)
        .all()
    )
    if not lines:
        return

    for rt in lines:
        sent = max(0, int(getattr(rt, "count_sent", 0) or 0))
        lost = max(0, int(getattr(rt, "count_lost", 0) or 0))
        returning = max(0, sent - lost)
        if returning > 0:
            row = (
                db.query(CityTroop)
                .filter(
                    CityTroop.city_id == raid.attacker_city_id,
                    CityTroop.troop_type_id == rt.troop_type_id,
                )
                .first()
            )
            if not row:
                row = CityTroop(
                    city_id=raid.attacker_city_id,
                    troop_type_id=rt.troop_type_id,
                    count=0,
                )
                db.add(row)
                db.flush()

            row.count = int(row.count) + int(returning)

        # ✅ consume the return so it can't happen twice
        rt.count_sent = max(int(rt.count_sent), int(rt.count_lost))

def _apply_casualties_at_arrival(db: Session, raid: Raid) -> None:
    """
    Resolve combat at arrival time.

    Uses:
      - attacker composition: raid_troops (count_sent)
      - defender composition: city_troops for target_city_id
      - troop stats: troop_types (attack, defense, hp)

    Effects:
      - sets attacker losses in raid_troops.count_lost
      - subtracts defender losses from city_troops.count
      - snapshots defender start + lost into raid_defender_troops (deterministic reports)
    """
    # Load attacker troop lines for this raid
    atk_lines = (
        db.query(RaidTroop)
        .filter(RaidTroop.raid_id == raid.id)
        .all()
    )
    if not atk_lines:
        return

    # ✅ Strong idempotency guard:
    # If we already snapshotted defender troops for this raid, do nothing.
    already = (
        db.query(RaidDefenderTroop)
        .filter(RaidDefenderTroop.raid_id == raid.id)
        .first()
    )
    if already:
        return

    atk_type_ids = [int(rt.troop_type_id) for rt in atk_lines]

    # Load ALL defender troops for the target city
    def_rows = (
        db.query(CityTroop)
        .filter(CityTroop.city_id == raid.target_city_id)
        .all()
    )
    def_by_type_id = {int(ct.troop_type_id): ct for ct in def_rows}

    # Union of troop types so power calc can see all relevant stats
    def_type_ids = [int(ct.troop_type_id) for ct in def_rows]
    all_type_ids = sorted(set(atk_type_ids + def_type_ids))

    if not all_type_ids:
        # no types exist anywhere; nothing to do
        for rt in atk_lines:
            rt.count_lost = 0
        return

    types = (
        db.query(TroopType)
        .filter(TroopType.id.in_(all_type_ids))
        .all()
    )
    tt_by_id = {int(tt.id): tt for tt in types}

    # ✅ Snapshot defender troops at impact time
    # (even if empty — but we only have rows for types that exist in city_troops)
    snap_by_type_id: dict[int, RaidDefenderTroop] = {}
    for ct in def_rows:
        tid = int(ct.troop_type_id)
        snap = RaidDefenderTroop(
            raid_id=raid.id,
            troop_type_id=tid,
            count_start=max(0, int(getattr(ct, "count", 0) or 0)),
            count_lost=0,
        )
        db.add(snap)
        snap_by_type_id[tid] = snap

    db.flush()  # allocate snapshot IDs (not required, but fine)

    # Compute total power
    atk_power = 0.0
    def_power = 0.0

    # Attacker power: sent * (attack + 0.10*hp)
    for rt in atk_lines:
        tid = int(rt.troop_type_id)
        tt = tt_by_id.get(tid)
        if not tt:
            continue

        sent = max(0, int(getattr(rt, "count_sent", 0) or 0))
        if sent <= 0:
            continue

        atk_power += sent * (float(tt.attack) + 0.10 * float(tt.hp))

    # Defender power: sum all defender troops * (defense + 0.10*hp)
    for ct in def_rows:
        tid = int(ct.troop_type_id)
        tt = tt_by_id.get(tid)
        if not tt:
            continue

        dcnt = max(0, int(getattr(ct, "count", 0) or 0))
        if dcnt <= 0:
            continue

        def_power += dcnt * (float(tt.defense) + 0.10 * float(tt.hp))

    # If no defenders, no losses
    if def_power <= 0:
        for rt in atk_lines:
            rt.count_lost = 0
        # snapshots exist but will all be 0 lost; that's fine
        return

    # If no attackers, nothing to do (shouldn’t happen if raid exists)
    if atk_power <= 0:
        return

    # Loss rates (your same tunable approach)
    ratio = def_power / (atk_power + def_power)  # 0..1

    attacker_loss_rate = min(0.60, max(0.05, ratio * 0.80))          # 5%..60%
    defender_loss_rate = min(0.75, max(0.10, (1.0 - ratio) * 1.00))  # 10%..75%

    # Apply attacker losses per attacker troop line
    for rt in atk_lines:
        sent = max(0, int(getattr(rt, "count_sent", 0) or 0))
        if sent <= 0:
            rt.count_lost = 0
            continue

        atk_lost = int(round(sent * attacker_loss_rate))
        atk_lost = max(0, min(sent, atk_lost))
        rt.count_lost = atk_lost

    # Apply defender losses per defender troop row (ALL defender types)
    for ct in def_rows:
        tid = int(ct.troop_type_id)
        dcnt = max(0, int(getattr(ct, "count", 0) or 0))
        if dcnt <= 0:
            continue

        def_lost = int(round(dcnt * defender_loss_rate))
        def_lost = max(0, min(dcnt, def_lost))

        ct.count = max(0, int(ct.count) - def_lost)

        snap = snap_by_type_id.get(tid)
        if snap:
            snap.count_lost = int(def_lost)

# ----------------------------
# Raids: two-stage resolver
# ----------------------------

def _resolve_arrivals_to_returning_at(db: Session, event_time: datetime) -> int:
    """
    Stage 1:
    enroute + arrives_at <= event_time => compute loot, subtract target, set returning + returns_at
    (attacker NOT credited yet)
    """
    due = (
        db.query(Raid)
        .filter(Raid.status == "enroute", Raid.arrives_at <= event_time)
        .all()
    )

    count = 0

    for r in due:
        attacker = db.query(City).filter(City.id == r.attacker_city_id).first()
        target = db.query(City).filter(City.id == r.target_city_id).first()

        if not attacker or not target:
            r.status = "resolved"
            r.resolved_at = event_time
            count += 1
            continue

        # Update storage/protected on both
        for c in (attacker, target):
            s = _recalc_storage_for_city(db, c.id)
            c.max_food = s["max_food"]
            c.max_wood = s["max_wood"]
            c.max_stone = s["max_stone"]
            c.max_iron = s["max_iron"]
            c.protected_food = s["protected_food"]
            c.protected_wood = s["protected_wood"]
            c.protected_stone = s["protected_stone"]
            c.protected_iron = s["protected_iron"]

        loot = _lootable(target)
        taken = _proportional_take(loot, r.carry_capacity)

        # Subtract from target (never below protected)
        target.food -= taken["food"]
        target.wood -= taken["wood"]
        target.stone -= taken["stone"]
        target.iron -= taken["iron"]

        target.food = max(target.food, target.protected_food)
        target.wood = max(target.wood, target.protected_wood)
        target.stone = max(target.stone, target.protected_stone)
        target.iron = max(target.iron, target.protected_iron)

        # Save loot on raid row (but DO NOT credit attacker yet)
        r.stolen_food = taken["food"]
        r.stolen_wood = taken["wood"]
        r.stolen_stone = taken["stone"]
        r.stolen_iron = taken["iron"]

        # Option B: resolve combat + record losses
        _apply_casualties_at_arrival(db, r)

        # --- PATCH (Stage 1 timing): respect outbound_seconds/return_seconds and only compute if missing ---
        # outbound_seconds: if missing/0, derive from timestamps (legacy rows)
        if getattr(r, "outbound_seconds", 0) <= 0:
            if r.created_at and r.arrives_at:
                r.outbound_seconds = max(
                    1, int((r.arrives_at - r.created_at).total_seconds())
                )
            else:
                r.outbound_seconds = 1

        # return_seconds: if missing/0, default to outbound_seconds (legacy rows)
        if getattr(r, "return_seconds", 0) <= 0:
            r.return_seconds = max(1, int(r.outbound_seconds))

        # returns_at: always re-anchor to arrives_at so timing is consistent
        base = r.arrives_at or event_time
        r.returns_at = base + timedelta(seconds=int(r.return_seconds))
        # END PATCH
        r.status = "returning"
        r.resolved_at = None
        count += 1

    return count


def _resolve_returns_to_resolved_at(db: Session, event_time: datetime) -> int:
    """
    Stage 2:
    returning + returns_at <= event_time => credit attacker, set resolved
    """
    due = (
        db.query(Raid)
        .filter(
            Raid.status == "returning",
            Raid.returns_at.isnot(None),  # prevents NULL compares / weird rows
            Raid.returns_at <= event_time,
        )
        .all()
    )

    count = 0

    for r in due:
        attacker = db.query(City).filter(City.id == r.attacker_city_id).first()

        # Defensive: stolen_* should never be NULL/negative, but clamp just in case.
        stolen_food = max(0, int(getattr(r, "stolen_food", 0) or 0))
        stolen_wood = max(0, int(getattr(r, "stolen_wood", 0) or 0))
        stolen_stone = max(0, int(getattr(r, "stolen_stone", 0) or 0))
        stolen_iron = max(0, int(getattr(r, "stolen_iron", 0) or 0))

        r.status = "resolved"
        r.resolved_at = event_time

        # Return troops (Option B)
        _return_troops_from_raid(db, r)

        if attacker:
            # Refresh storage so max_* (and protected_*) match current buildings.
            s = _recalc_storage_for_city(db, attacker.id)
            attacker.max_food = s["max_food"]
            attacker.max_wood = s["max_wood"]
            attacker.max_stone = s["max_stone"]
            attacker.max_iron = s["max_iron"]

            # Optional: keep protected_* in sync too
            attacker.protected_food = s["protected_food"]
            attacker.protected_wood = s["protected_wood"]
            attacker.protected_stone = s["protected_stone"]
            attacker.protected_iron = s["protected_iron"]

            # Credit loot, capped by max storage
            attacker.food = min(attacker.max_food, attacker.food + stolen_food)
            attacker.wood = min(attacker.max_wood, attacker.wood + stolen_wood)
            attacker.stone = min(attacker.max_stone, attacker.stone + stolen_stone)
            attacker.iron = min(attacker.max_iron, attacker.iron + stolen_iron)

        # NEW: drop raid-result mail into both players' inboxes
        # (Use r.id — your loop var is r)
        send_raid_result_mail(db, raid_id=r.id, now=event_time)

        count += 1

    return count

# ----------------------------
# Tiny wrappers (use "now")
# ----------------------------

def _resolve_arrivals_to_returning(db: Session, now: datetime) -> int:
    """
    Wrapper for Stage 1 using current tick time.
    """
    return _resolve_arrivals_to_returning_at(db, now)


def _resolve_returns_to_resolved(db: Session, now: datetime) -> int:
    """
    Wrapper for Stage 2 using current tick time.
    """
    return _resolve_returns_to_resolved_at(db, now)


# ----------------------------
# Upgrades: event-time resolver
# ----------------------------

def _complete_due_upgrades_at(db: Session, event_time: datetime) -> int:
    due = db.query(Upgrade).filter(Upgrade.completes_at <= event_time).all()
    completed = 0
    touched_city_ids = set()

    for up in due:
        b = (
            db.query(Building)
            .filter(Building.city_id == up.city_id, Building.type == up.building_type)
            .first()
        )
        if b:
            b.level = up.to_level
            touched_city_ids.add(up.city_id)

        db.delete(up)
        completed += 1

    # Apply immediate effects for completed upgrades at this same event_time
    if touched_city_ids:
        for city_id in touched_city_ids:
            city = db.query(City).filter(City.id == city_id).first()
            if not city:
                continue

            # Keep level mirror (you already expose townhall_level on City)
            keep = (
                db.query(Building)
                .filter(Building.city_id == city_id, Building.type == "townhall")
                .first()
            )
            if keep:
                city.townhall_level = keep.level

            # Refresh storage + protection + rates immediately
            rates = _recalc_rates_for_city(db, city_id)
            city.food_rate = rates["food_rate"]
            city.wood_rate = rates["wood_rate"]
            city.stone_rate = rates["stone_rate"]
            city.iron_rate = rates["iron_rate"]

            storage = _recalc_storage_for_city(db, city_id)
            city.max_food = storage["max_food"]
            city.max_wood = storage["max_wood"]
            city.max_stone = storage["max_stone"]
            city.max_iron = storage["max_iron"]
            city.protected_food = storage["protected_food"]
            city.protected_wood = storage["protected_wood"]
            city.protected_stone = storage["protected_stone"]
            city.protected_iron = storage["protected_iron"]

            # Clamp (shouldn’t usually decrease, but safe)
            city.food = min(city.food, city.max_food)
            city.wood = min(city.wood, city.max_wood)
            city.stone = min(city.stone, city.max_stone)
            city.iron = min(city.iron, city.max_iron)

    return completed


def _next_event_time(db: Session, after: datetime, hard_stop: datetime) -> Optional[datetime]:
    """
    Find the next interesting time > after and <= hard_stop among:
    - next raid arrival (enroute.arrives_at)
    - next raid return  (returning.returns_at)
    - next upgrade complete (upgrade.completes_at)
    Returns None if none exist (meaning: jump to hard_stop).
    """
    next_times = []

    next_arrival = (
        db.query(Raid)
        .filter(Raid.status == "enroute", Raid.arrives_at > after, Raid.arrives_at <= hard_stop)
        .order_by(Raid.arrives_at.asc())
        .first()
    )
    if next_arrival:
        next_times.append(next_arrival.arrives_at)

    next_return = (
        db.query(Raid)
        .filter(Raid.status == "returning", Raid.returns_at > after, Raid.returns_at <= hard_stop)
        .order_by(Raid.returns_at.asc())
        .first()
    )
    if next_return and next_return.returns_at:
        next_times.append(next_return.returns_at)

    next_upgrade = (
        db.query(Upgrade)
        .filter(Upgrade.completes_at > after, Upgrade.completes_at <= hard_stop)
        .order_by(Upgrade.completes_at.asc())
        .first()
    )
    if next_upgrade:
        next_times.append(next_upgrade.completes_at)

    if not next_times:
        return None

    return min(next_times)


# ----------------------------
# Main tick runner
# ----------------------------

def tick_all_cities(db: Session, now: datetime) -> Dict[str, object]:
    cities = db.query(City).all()

    # Start from the earliest last_tick_at we have (so event-time stepping is monotonic)
    start = now
    for c in cities:
        if c.last_tick_at and c.last_tick_at < start:
            start = c.last_tick_at

    current_time = start

    total_minutes = 0
    ticked_city_ids: set[int] = set()
    upgrades_completed = 0

    raids_arrived = 0
    raids_returned = 0

    while True:
        nxt = _next_event_time(db, current_time, now)
        event_time = nxt if nxt is not None else now

        # Apply city production up to this event_time
        for c in cities:
            m = apply_city_tick(c, event_time, db)
            if m > 0:
                total_minutes += m
                ticked_city_ids.add(c.id)

        # Resolve upgrades/raids at this event_time
        upgrades_completed += _complete_due_upgrades_at(db, event_time)

        raids_arrived += _resolve_arrivals_to_returning_at(db, event_time)
        raids_returned += _resolve_returns_to_resolved_at(db, event_time)

        current_time = event_time

        if event_time >= now:
            break

    db.commit()

    return {
        "cities_total": len(cities),
        "cities_ticked": len(ticked_city_ids),  # unique cities that had minutes applied
        "minutes_applied_total": total_minutes,
        "upgrades_completed": upgrades_completed,
        "raids_arrived": raids_arrived,
        "raids_returned": raids_returned,
        "at": now.isoformat(),
    }
