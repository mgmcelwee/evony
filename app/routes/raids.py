# app/routes/raids.py
from __future__ import annotations

import math
import secrets
import os
import html
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.config import ADMIN_KEY
from app.database import get_db
from app.models.city import City
from app.models.raid import Raid
from app.models.building import Building
from app.models.troop_type import TroopType
from app.models.city_troop import CityTroop
from app.models.raid_troop import RaidTroop
from app.models.raid_defender_troop import RaidDefenderTroop
from app.routes.auth import get_current_user
from app.routes.tick_util import tick_world_now
from app.game.tick import _recalc_storage_for_city, _lootable, _proportional_take

router = APIRouter(prefix="/raids", tags=["raids"])

SECONDS_PER_TILE_DEFAULT = 5  # tweak feel here
BASE_TROOP_SPEED = 100  # speed=100 => no change to base travel time
RECALL_RETURN_FACTOR = 0.5
# 0.5 = twice as fast on the way home when recalling a returning march.
# 1.0 = no speedup
# 0.25 = 4x speedup

def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)

def _compute_seconds_from_troop_speed(base_seconds: int, slowest_speed: int) -> int:
    """
    TroopType.speed: bigger = faster
    We scale time by (BASE_TROOP_SPEED / slowest_speed).
    Example:
      slowest_speed=100 => factor 1.0 (no change)
      slowest_speed=200 => factor 0.5 (twice as fast)
      slowest_speed=50  => factor 2.0 (twice as slow)
    """
    slowest_speed = max(1, int(slowest_speed or BASE_TROOP_SPEED))
    factor = BASE_TROOP_SPEED / float(slowest_speed)
    return max(1, int(math.ceil(base_seconds * factor)))


def _resolve_and_validate_troops(
    db: Session,
    attacker_city_id: int,
    troops: list[TroopSendItem],
) -> tuple[dict[int, int], int, int, dict]:
    """
    Returns:
      - by_type_id: {troop_type_id: count_sent}
      - computed_carry_capacity
      - slowest_speed
      - debug breakdown (optional to return in response)
    """
    if not troops:
        raise HTTPException(status_code=400, detail="troops is required")

    # Normalize + aggregate in case client repeats codes
    requested_by_code: dict[str, int] = {}
    for t in troops:
        code = (t.code or "").strip()
        if not code:
            continue
        requested_by_code[code] = requested_by_code.get(code, 0) + int(t.count)

    if not requested_by_code:
        raise HTTPException(status_code=400, detail="troops is required")

    codes = list(requested_by_code.keys())

    # Load troop types in one query
    troop_types = db.query(TroopType).filter(TroopType.code.in_(codes)).all()
    tt_by_code = {tt.code: tt for tt in troop_types}

    missing = [c for c in codes if c not in tt_by_code]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "Unknown troop code(s)", "codes": missing},
        )

    # Map to type_id -> requested count
    by_type_id: dict[int, int] = {}
    slowest_speed: int | None = None
    computed_capacity = 0

    for code, cnt in requested_by_code.items():
        tt = tt_by_code[code]
        by_type_id[int(tt.id)] = by_type_id.get(int(tt.id), 0) + int(cnt)

        computed_capacity += int(cnt) * int(tt.carry)

        s = int(tt.speed or BASE_TROOP_SPEED)
        slowest_speed = s if (slowest_speed is None) else min(slowest_speed, s)

    if slowest_speed is None:
        slowest_speed = BASE_TROOP_SPEED

    # Load city troop rows for those troop types
    rows = (
        db.query(CityTroop)
        .filter(
            CityTroop.city_id == attacker_city_id,
            CityTroop.troop_type_id.in_(list(by_type_id.keys())),
        )
        .all()
    )
    have_by_type_id = {int(r.troop_type_id): int(r.count) for r in rows}

    # Validate enough troops
    insufficient = []
    for troop_type_id, want in by_type_id.items():
        have = have_by_type_id.get(int(troop_type_id), 0)
        if have < want:
            insufficient.append(
                {
                    "troop_type_id": int(troop_type_id),
                    "want": int(want),
                    "have": int(have),
                }
            )

    if insufficient:
        raise HTTPException(
            status_code=409,
            detail={"error": "Not enough troops", "insufficient": insufficient},
        )

    debug = {
        "computed_carry_capacity": int(computed_capacity),
        "slowest_speed": int(slowest_speed),
    }
    return by_type_id, int(computed_capacity), int(slowest_speed), debug

def _apply_speed_pct(base_seconds: int, speed_pct: int) -> int:
    """
    speed_pct: 0 = no buff
    25 = 25% faster (time * 0.75)
    """
    speed_pct = max(0, int(speed_pct or 0))
    multiplier = max(0.05, 1.0 - (speed_pct / 100.0))  # never hit 0
    return max(1, int(math.ceil(base_seconds * multiplier)))

def _advance_to_returning_and_steal(db: Session, raid: Raid, now: datetime) -> None:
    """
    If a raid is enroute but its arrives_at is already in the past (late tick),
    we still want the raid to "hit" the target (steal) and become returning.
    This mirrors your tick Stage 1 logic.
    """
    attacker = db.query(City).filter(City.id == raid.attacker_city_id).first()
    target = db.query(City).filter(City.id == raid.target_city_id).first()

    if not attacker or not target:
        raid.status = "resolved"
        raid.resolved_at = now
        return

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
    taken = _proportional_take(loot, raid.carry_capacity)

    # Subtract from target (never below protected)
    target.food -= taken["food"]
    target.wood -= taken["wood"]
    target.stone -= taken["stone"]
    target.iron -= taken["iron"]

    target.food = max(target.food, target.protected_food)
    target.wood = max(target.wood, target.protected_wood)
    target.stone = max(target.stone, target.protected_stone)
    target.iron = max(target.iron, target.protected_iron)

    # Save loot on raid row (do NOT credit attacker yet; that happens at returns_at)
    raid.stolen_food = taken["food"]
    raid.stolen_wood = taken["wood"]
    raid.stolen_stone = taken["stone"]
    raid.stolen_iron = taken["iron"]

    # Ensure returns_at exists (use stored return_seconds if present)
    if not raid.returns_at:
        base = raid.arrives_at or now
        rs = raid.return_seconds or 0
        if rs <= 0:
            rs = raid.outbound_seconds or 0
            if rs <= 0 and raid.created_at and raid.arrives_at:
                rs = int((raid.arrives_at - raid.created_at).total_seconds())
            rs = max(1, int(rs))
            raid.return_seconds = rs
        raid.returns_at = base + timedelta(seconds=int(rs))

    raid.status = "returning"
    raid.resolved_at = None

def _now_utc() -> datetime:
    return datetime.utcnow()

def _distance_tiles(a: City, b: City) -> float:
    dx = (b.x - a.x)
    dy = (b.y - a.y)
    return (dx * dx + dy * dy) ** 0.5


def _compute_travel_seconds(distance_tiles: float, seconds_per_tile: int) -> int:
    return max(1, int(round(distance_tiles * seconds_per_tile)))

def _carry_capacity_from_barracks(db: Session, city_id: int) -> int:
    """
    Age 1: Tie raid carry capacity to Barracks level.
    L1=500, L2=700, L3=950, L4=1250, L5=1600 ... (simple curve)
    """
    barracks = (
        db.query(Building)
        .filter(Building.city_id == city_id, Building.type == "barracks")
        .first()
    )
    lvl = int(getattr(barracks, "level", 1) or 1)

    # Simple “Age 1” curve (tune later):
    return int(500 + (lvl - 1) * 200 + max(0, (lvl - 1)) ** 2 * 50)

def _keep_level(db: Session, city_id: int) -> int:
    keep = (
        db.query(Building)
        .filter(Building.city_id == city_id, Building.type == "townhall")
        .first()
    )
    return int(getattr(keep, "level", 1) or 1)

def _reserve_troops_for_raid(
    db: Session,
    city_id: int,
    troops: list[dict],
) -> dict:
    """
    Validates + subtracts troops from city_troops.
    Returns:
      {
        "lines": [{"troop_type_id", "code", "count_sent", "speed", "carry"}...],
        "army_carry": int,
        "min_speed": int,
      }
    """
    if not troops:
        raise HTTPException(status_code=400, detail="troops list cannot be empty")

    # Normalize + combine duplicates by code
    combined: dict[str, int] = {}
    for t in troops:
        code = str(t["code"]).strip()
        cnt = int(t["count"])
        if not code or cnt <= 0:
            raise HTTPException(status_code=400, detail="Invalid troop line")
        combined[code] = combined.get(code, 0) + cnt

    codes = list(combined.keys())

    # Load troop types
    types = (
        db.query(TroopType)
        .filter(TroopType.code.in_(codes))
        .all()
    )
    by_code = {tt.code: tt for tt in types}
    missing = [c for c in codes if c not in by_code]
    if missing:
        raise HTTPException(status_code=400, detail={"error": "Unknown troop code(s)", "codes": missing})

    # Load current city troops
    type_ids = [by_code[c].id for c in codes]
    city_rows = (
        db.query(CityTroop)
        .filter(CityTroop.city_id == city_id, CityTroop.troop_type_id.in_(type_ids))
        .all()
    )
    city_by_type = {ct.troop_type_id: ct for ct in city_rows}

    # Validate enough troops
    for code, need in combined.items():
        tt = by_code[code]
        have = int(getattr(city_by_type.get(tt.id), "count", 0) or 0)
        if have < need:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "Not enough troops",
                    "code": code,
                    "requested": int(need),
                    "available": int(have),
                },
            )

    # Subtract (reserve)
    for code, need in combined.items():
        tt = by_code[code]
        row = city_by_type.get(tt.id)
        if not row:
            # If row is missing, it implies 0 troops, but we already validated.
            row = CityTroop(city_id=city_id, troop_type_id=tt.id, count=0)
            db.add(row)
            db.flush()
        row.count = int(row.count) - int(need)

    # Build raid troop lines + stats
    lines = []
    army_carry = 0
    min_speed = None

    for code, sent in combined.items():
        tt = by_code[code]
        spd = int(getattr(tt, "speed", 100) or 100)
        car = int(getattr(tt, "carry", 1) or 1)

        army_carry += int(sent) * int(car)
        min_speed = spd if min_speed is None else min(min_speed, spd)

        lines.append(
            {
                "troop_type_id": tt.id,
                "code": tt.code,
                "count_sent": int(sent),
                "speed": int(spd),
                "carry": int(car),
            }
        )

    return {
        "lines": lines,
        "army_carry": int(army_carry),
        "min_speed": int(min_speed or 100),
    }

def _apply_troop_speed_to_base_seconds(base_seconds: int, min_speed: int, reference_speed: int = 100) -> int:
    """
    speed is a rating where larger = faster.
    We scale time by (reference_speed / min_speed).
    """
    min_speed = max(1, int(min_speed))
    base_seconds = max(1, int(base_seconds))
    scaled = base_seconds * (reference_speed / float(min_speed))
    return max(1, int(math.ceil(scaled)))

def _max_simultaneous_raids(db: Session, city_id: int) -> int:
    k = _keep_level(db, city_id)
    # Age 1 curve (tune freely):
    if k <= 2:
        return 1
    if k <= 4:
        return 2
    if k <= 6:
        return 3
    return 4  # cap

def _active_raids_count(db: Session, attacker_city_id: int) -> int:
    return int(
        db.query(func.count(Raid.id))
        .filter(
            Raid.attacker_city_id == attacker_city_id,
            Raid.status.in_(["enroute", "returning"]),
        )
        .scalar()
        or 0
    )

def _time_remaining_seconds(now: datetime, raid: Raid) -> Optional[int]:
    if raid.status == "enroute" and raid.arrives_at:
        return max(0, int((raid.arrives_at - now).total_seconds()))
    if raid.status == "returning" and raid.returns_at:
        return max(0, int((raid.returns_at - now).total_seconds()))
    return None

def _compute_raid_timing(attacker: City, target: City, now: datetime, base_seconds: int) -> dict:
    """
    Shared timing logic for:
      - GET /raids/preview
      - POST /raids (create_raid)

    Returns dict with:
      distance_tiles, base_seconds, outbound_seconds, return_seconds, arrives_at, returns_at
    """
    distance = _distance_tiles(attacker, target)

    outbound_seconds = _apply_speed_pct(base_seconds, getattr(attacker, "march_speed_pct", 0))
    return_seconds = _apply_speed_pct(base_seconds, getattr(attacker, "return_speed_pct", 0))

    arrives_at = now + timedelta(seconds=outbound_seconds)
    returns_at = arrives_at + timedelta(seconds=return_seconds)

    return {
        "distance_tiles": float(distance),
        "base_seconds": int(base_seconds),
        "outbound_seconds": int(outbound_seconds),
        "return_seconds": int(return_seconds),
        "arrives_at": arrives_at,
        "returns_at": returns_at,
    }

def _atk_unit_power(tt: TroopType) -> float:
    # matches tick.py attacker power model
    return float(getattr(tt, "attack", 0) or 0) + 0.10 * float(getattr(tt, "hp", 0) or 0)

def _def_unit_power(tt: TroopType) -> float:
    # matches tick.py defender power model
    return float(getattr(tt, "defense", 0) or 0) + 0.10 * float(getattr(tt, "hp", 0) or 0)

def _loss_pct(lost: int, start: int) -> float:
    if start <= 0:
        return 0.0
    return round((float(lost) / float(start)) * 100.0, 2)

def _round2(x: float) -> float:
    return round(float(x), 2)

class TroopSendItem(BaseModel):
    # Use code so your API is stable across DB IDs
    code: str = Field(..., min_length=1, max_length=32)
    count: int = Field(..., ge=1)

class RaidCreateRequest(BaseModel):
    attacker_city_id: int
    target_city_id: int

    # Optional: for admin/testing only. Normal players should omit.
    carry_capacity: Optional[int] = Field(None, ge=1, le=10_000_000)

    # Optional override for testing. If omitted, computed from distance.
    travel_seconds: Optional[int] = Field(None, ge=1, le=60 * 60 * 24)

    # Option B: real army composition (optional for backward compatibility)
    troops: Optional[List[TroopSendItem]] = None

@router.get("/preview")
def preview_raid(
    attacker_city_id: int,
    target_city_id: int,
    carry_capacity: int = 1500,
    travel_seconds: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:

    if attacker_city_id == target_city_id:
        raise HTTPException(status_code=400, detail="Cannot raid the same city")

    attacker = (
        db.query(City)
        .filter(City.id == attacker_city_id, City.owner_id == current_user.id)
        .first()
    )
    if not attacker:
        raise HTTPException(status_code=404, detail="Attacker city not found")

    # -------------------------------
    # Option A: preview shows
    # - computed carry capacity (Barracks)
    # - raid cap info (Keep-based)
    # -------------------------------
    computed_capacity = _carry_capacity_from_barracks(db, attacker.id)

    # Admin can "what-if" preview a different carry_capacity via query param
    is_admin = (x_admin_key == ADMIN_KEY)
    effective_capacity = computed_capacity
    if is_admin and carry_capacity is not None:
        effective_capacity = int(carry_capacity)

    keep_level = _keep_level(db, attacker.id)
    active_raids = _active_raids_count(db, attacker.id)
    max_allowed = _max_simultaneous_raids(db, attacker.id)

    cap_blocked = (active_raids >= max_allowed) and (not is_admin)

    target = db.query(City).filter(City.id == target_city_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target city not found")

    if target.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot raid your own city")

    now = _now_utc()

    # base time (no buffs)
    if travel_seconds is None:
        base_seconds = _compute_travel_seconds(
            _distance_tiles(attacker, target),
            SECONDS_PER_TILE_DEFAULT,
        )
    else:
        base_seconds = int(travel_seconds)

    timing = _compute_raid_timing(attacker, target, now, base_seconds)

    return {
        "attacker_city_id": attacker.id,
        "target_city_id": target.id,

        # Carry capacity (Age 1)
        "carry_capacity": int(effective_capacity),
        "computed_carry_capacity": int(computed_capacity),

        # Raid cap (Keep-based)
        "keep_level": int(keep_level),
        "active_raids": int(active_raids),
        "max_allowed_raids": int(max_allowed),
        "cap_blocked": bool(cap_blocked),
        "cap_reason": None if not cap_blocked else {
            "error": "Too many active raids",
            "active_raids": int(active_raids),
            "max_allowed": int(max_allowed),
            "keep_level": int(keep_level),
            "rule": "simultaneous raids scale with Keep level",
        },

        "march_speed_pct": int(getattr(attacker, "march_speed_pct", 0) or 0),
        "return_speed_pct": int(getattr(attacker, "return_speed_pct", 0) or 0),
        "distance_tiles": timing["distance_tiles"],
        "travel_seconds": timing["base_seconds"],
        "outbound_seconds": timing["outbound_seconds"],
        "return_seconds": timing["return_seconds"],
        "arrives_at": timing["arrives_at"].isoformat(),
        "returns_at": timing["returns_at"].isoformat(),
    }

@router.post("")
def create_raid(
    payload: RaidCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if payload.attacker_city_id == payload.target_city_id:
        raise HTTPException(status_code=400, detail="Cannot raid the same city")

    attacker = (
        db.query(City)
        .filter(City.id == payload.attacker_city_id, City.owner_id == current_user.id)
        .first()
    )
    if not attacker:
        raise HTTPException(status_code=404, detail="Attacker city not found")

    # Admin flag (used for cap bypass + carry override)
    is_admin = (x_admin_key == ADMIN_KEY)

    # --------------------------------------------------
    # Age 1: Limit simultaneous raids (Keep-based)
    # --------------------------------------------------
    keep_level = _keep_level(db, attacker.id)
    max_allowed = _max_simultaneous_raids(db, attacker.id)
    active_raids = _active_raids_count(db, attacker.id)

    if active_raids >= max_allowed and not is_admin:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Too many active raids",
                "active_raids": int(active_raids),
                "max_allowed": int(max_allowed),
                "keep_level": int(keep_level),
                "rule": "simultaneous raids scale with Keep level",
            },
        )

    # --------------------------------------------------
    # Load target
    # --------------------------------------------------
    target = db.query(City).filter(City.id == payload.target_city_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Target city not found")

    if target.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot raid your own city")

    # --------------------------------------------------
    # Option B: Troops REQUIRED (real army composition)
    # --------------------------------------------------
    if not payload.troops:
        raise HTTPException(
            status_code=400,
            detail={"error": "troops is required", "rule": "Option B real army composition"},
        )

    # Everything below writes to DB; protect with rollback on any failure.
    try:
        by_type_id, computed_army_carry, slowest_speed, troop_debug = _resolve_and_validate_troops(
            db=db,
            attacker_city_id=attacker.id,
            troops=payload.troops,
        )

        # --------------------------------------------------
        # Reserve/subtract troops from city_troops
        # --------------------------------------------------
        city_rows = (
            db.query(CityTroop)
            .filter(
                CityTroop.city_id == attacker.id,
                CityTroop.troop_type_id.in_(list(by_type_id.keys())),
            )
            .all()
        )
        city_by_type_id = {int(r.troop_type_id): r for r in city_rows}

        for troop_type_id, sent in by_type_id.items():
            row = city_by_type_id.get(int(troop_type_id))
            if not row:
                row = CityTroop(city_id=attacker.id, troop_type_id=int(troop_type_id), count=0)
                db.add(row)
                db.flush()
            row.count = int(row.count) - int(sent)

        now = _now_utc()

        # --------------------------------------------------
        # 1) Base travel time (distance -> seconds)
        # --------------------------------------------------
        if payload.travel_seconds is None:
            base_seconds = _compute_travel_seconds(
                _distance_tiles(attacker, target),
                SECONDS_PER_TILE_DEFAULT,
            )
        else:
            base_seconds = int(payload.travel_seconds)

        # Scale by slowest troop speed
        base_seconds = _compute_seconds_from_troop_speed(base_seconds, slowest_speed)

        # --------------------------------------------------
        # 2) Apply city buffs + schedule timestamps
        # --------------------------------------------------
        timing = _compute_raid_timing(attacker, target, now, base_seconds)

        arrives_at = timing["arrives_at"]
        returns_at = timing["returns_at"]
        outbound_seconds = timing["outbound_seconds"]
        return_seconds = timing["return_seconds"]
        distance_tiles = timing["distance_tiles"]

        # --------------------------------------------------
        # 3) Carry capacity = min(Barracks cap, Army carry)
        # --------------------------------------------------
        barracks_cap = _carry_capacity_from_barracks(db, attacker.id)
        carry_capacity = int(min(int(barracks_cap), int(computed_army_carry)))

        if payload.carry_capacity is not None:
            if not is_admin:
                raise HTTPException(status_code=403, detail="Forbidden")
            carry_capacity = int(payload.carry_capacity)

        # --------------------------------------------------
        # 4) Create raid row
        # --------------------------------------------------
        raid_row = Raid(
            attacker_city_id=attacker.id,
            target_city_id=target.id,
            carry_capacity=carry_capacity,
            status="enroute",
            arrives_at=arrives_at,
            returns_at=returns_at,
            resolved_at=None,
            outbound_seconds=outbound_seconds,
            return_seconds=return_seconds,
        )

        db.add(raid_row)
        db.flush()  # get raid_row.id without committing yet

        # Record what was sent (raid_troops)
        for troop_type_id, sent in by_type_id.items():
            db.add(
                RaidTroop(
                    raid_id=raid_row.id,
                    troop_type_id=int(troop_type_id),
                    count_sent=int(sent),
                    count_lost=0,
                )
            )

        db.commit()
        db.refresh(raid_row)

        return {
            "raid_id": raid_row.id,
            "report_url": f"/raids/{raid_row.id}/report.html",
            "report_json_url": f"/raids/{raid_row.id}/report",
            "status": raid_row.status,
            "attacker_city_id": raid_row.attacker_city_id,
            "target_city_id": raid_row.target_city_id,
            "carry_capacity": raid_row.carry_capacity,
            "created_at": raid_row.created_at.isoformat() if raid_row.created_at else None,
            "arrives_at": raid_row.arrives_at.isoformat() if raid_row.arrives_at else None,
            "returns_at": raid_row.returns_at.isoformat() if raid_row.returns_at else None,
            "distance_tiles": float(distance_tiles),
            "travel_seconds": int(base_seconds),
            "outbound_seconds": int(outbound_seconds),
            "return_seconds": int(return_seconds),
            "time_remaining_seconds": _time_remaining_seconds(now, raid_row),
            "troops": [{"troop_type_id": int(tid), "count_sent": int(cnt)} for tid, cnt in by_type_id.items()],
            "troop_speed_slowest": int(troop_debug["slowest_speed"]),
            "army_carry_capacity": int(troop_debug["computed_carry_capacity"]),
            "barracks_carry_cap": int(barracks_cap),
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

@router.post("/{raid_id}/recall")
def recall_raid(
    raid_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    now = tick_world_now(db)
    is_admin = _is_admin(x_admin_key)

    # Raid lookup: same pattern as get_raid
    q = db.query(Raid).filter(Raid.id == raid_id)
    if not is_admin:
        q = (
            q.join(City, City.id == Raid.attacker_city_id)
             .filter(City.owner_id == current_user.id)
        )

    raid = q.first()
    if not raid:
        raise HTTPException(status_code=404, detail="Raid not found")

    if raid.status == "resolved":
        raise HTTPException(status_code=400, detail="Raid already resolved")

    # Attacker lookup: same “admin vs owner” pattern
    cq = db.query(City).filter(City.id == raid.attacker_city_id)
    if not is_admin:
        cq = cq.filter(City.owner_id == current_user.id)

    attacker = cq.first()
    if not attacker:
        raise HTTPException(status_code=404, detail="Attacker city not found")

    return_speed_pct = getattr(attacker, "return_speed_pct", 0)

    # --- Recall logic (unchanged from your current version) ---
    if raid.status == "enroute":
        if raid.arrives_at and now >= raid.arrives_at:
            _advance_to_returning_and_steal(db, raid, now)

            if getattr(raid, "return_seconds", 0) <= 0:
                base = getattr(raid, "outbound_seconds", 0)
                if base <= 0 and raid.created_at and raid.arrives_at:
                    base = int((raid.arrives_at - raid.created_at).total_seconds())
                base = max(1, int(base))
                raid.return_seconds = _apply_speed_pct(base, return_speed_pct)

            if not raid.returns_at:
                base_time = raid.arrives_at or now
                raid.returns_at = base_time + timedelta(seconds=int(raid.return_seconds))

        else:
            elapsed = 1
            if raid.created_at:
                elapsed = max(1, int((now - raid.created_at).total_seconds()))

            raid.outbound_seconds = elapsed
            raid.status = "returning"
            raid.resolved_at = None

            rs = _apply_speed_pct(elapsed, return_speed_pct)
            raid.return_seconds = rs
            raid.returns_at = now + timedelta(seconds=rs)

            raid.stolen_food = 0
            raid.stolen_wood = 0
            raid.stolen_stone = 0
            raid.stolen_iron = 0

    elif raid.status == "returning":
        if not raid.returns_at:
            raid.returns_at = now + timedelta(seconds=1)

        remaining = max(1, int((raid.returns_at - now).total_seconds()))
        sped_up = max(1, int(math.ceil(remaining * RECALL_RETURN_FACTOR)))
        final_remaining = _apply_speed_pct(sped_up, return_speed_pct)

        raid.return_seconds = final_remaining
        raid.returns_at = now + timedelta(seconds=final_remaining)

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported raid status: {raid.status}")

    db.commit()
    db.refresh(raid)

    # Response shape: same top-level fields as get_raid
    return {
        "raid_id": raid.id,
        "status": raid.status,
        "attacker_city_id": raid.attacker_city_id,
        "target_city_id": raid.target_city_id,
        "carry_capacity": raid.carry_capacity,
        "created_at": raid.created_at.isoformat() if raid.created_at else None,
        "arrives_at": raid.arrives_at.isoformat() if raid.arrives_at else None,
        "returns_at": raid.returns_at.isoformat() if raid.returns_at else None,
        "resolved_at": raid.resolved_at.isoformat() if raid.resolved_at else None,
        "time_remaining_seconds": _time_remaining_seconds(now, raid),
        "stolen": {
            "food": raid.stolen_food,
            "wood": raid.stolen_wood,
            "stone": raid.stolen_stone,
            "iron": raid.stolen_iron,
        },
        # Optional: tuck extra tuning fields under a debug key
        "debug": {
            "outbound_seconds": int(getattr(raid, "outbound_seconds", 0) or 0),
            "return_seconds": int(getattr(raid, "return_seconds", 0) or 0),
            "return_speed_pct": int(return_speed_pct or 0),
            "recall_return_factor": float(RECALL_RETURN_FACTOR),
        },
    }
@router.get("")
def list_my_raids(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
    status: Optional[str] = None,
    limit: int = 50,
) -> dict:
    limit = max(1, min(limit, 500))
    now = tick_world_now(db)

    # order: enroute first, then returning, then resolved; newest first within group
    status_rank = case(
        (Raid.status == "enroute", 0),
        (Raid.status == "returning", 1),
        else_=2,
    )

    q = db.query(Raid)

    if not _is_admin(x_admin_key):
        q = (
            q.join(City, City.id == Raid.attacker_city_id)
             .filter(City.owner_id == current_user.id)
        )

    if status:
        q = q.filter(Raid.status == status)

    raids = (
        q.order_by(status_rank.asc(), Raid.id.desc())
         .limit(limit)
         .all()
    )

    return {
        "raids": [
            {
                "raid_id": r.id,
                "report_url": f"/raids/{r.id}/report.html",
                "report_json_url": f"/raids/{r.id}/report",
                "status": r.status,
                "attacker_city_id": r.attacker_city_id,
                "target_city_id": r.target_city_id,
                "carry_capacity": r.carry_capacity,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "arrives_at": r.arrives_at.isoformat() if r.arrives_at else None,
                "returns_at": r.returns_at.isoformat() if r.returns_at else None,
                "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                "time_remaining_seconds": _time_remaining_seconds(now, r),
                "stolen": {
                    "food": r.stolen_food,
                    "wood": r.stolen_wood,
                    "stone": r.stolen_stone,
                    "iron": r.stolen_iron,
                },
            }
            for r in raids
        ]
    }

def _build_combat_report(
    *,
    raid_id: int,
    db: Session,
    current_user,
    x_admin_key: str | None,
    include_power_totals_in_main_blocks: bool = True,
    sort_damage_by_power_lost: bool = True,
    include_outcome_hint: bool = True,
) -> dict:
    now = tick_world_now(db)
    is_admin = _is_admin(x_admin_key)

    # --- Raid lookup (admin can view any; normal users must own attacker city) ---
    q = db.query(Raid)
    if not is_admin:
        q = (
            q.join(City, City.id == Raid.attacker_city_id)
             .filter(City.owner_id == current_user.id)
        )

    raid = q.filter(Raid.id == raid_id).first()
    if not raid:
        raise HTTPException(status_code=404, detail="Raid not found")

    attacker = db.query(City).filter(City.id == raid.attacker_city_id).first()
    target = db.query(City).filter(City.id == raid.target_city_id).first()

    # -----------------------------
    # Attacker troop lines (sent/lost) + troop metadata
    # -----------------------------
    atk_lines = (
        db.query(RaidTroop, TroopType)
        .join(TroopType, TroopType.id == RaidTroop.troop_type_id)
        .filter(RaidTroop.raid_id == raid.id)
        .order_by(TroopType.id.asc())
        .all()
    )

    attacker_troops: list[dict] = []
    for rt, tt in atk_lines:
        sent = int(getattr(rt, "count_sent", 0) or 0)
        lost = int(getattr(rt, "count_lost", 0) or 0)
        returning = max(0, sent - lost)
        attacker_troops.append(
            {
                "troop_type_id": int(tt.id),
                "code": tt.code,
                "name": tt.name,
                "tier": int(tt.tier),
                "sent": sent,
                "lost": lost,
                "returning": returning,
                "stats": {
                    "attack": int(tt.attack),
                    "defense": int(tt.defense),
                    "hp": int(tt.hp),
                    "speed": int(tt.speed),
                    "carry": int(tt.carry),
                },
            }
        )

    atk_totals: dict[str, int | float] = {
        "sent": sum(t["sent"] for t in attacker_troops),
        "lost": sum(t["lost"] for t in attacker_troops),
        "returning": sum(t["returning"] for t in attacker_troops),
    }

    # -----------------------------
    # Defender troops (snapshot preferred)
    # -----------------------------
    defender_troops: list[dict] = []
    defender_source = "raid_defender_troops"
    defender_note = (
        "Defender troops are sourced from the per-raid snapshot "
        "(start/lost/remaining), so reports are deterministic."
    )

    snap_rows = (
        db.query(RaidDefenderTroop, TroopType)
        .join(TroopType, TroopType.id == RaidDefenderTroop.troop_type_id)
        .filter(RaidDefenderTroop.raid_id == raid.id)
        .order_by(TroopType.id.asc())
        .all()
    )

    if snap_rows:
        for rdt, tt in snap_rows:
            start = int(getattr(rdt, "count_start", 0) or 0)
            lost = int(getattr(rdt, "count_lost", 0) or 0)
            remaining = max(0, start - lost)
            defender_troops.append(
                {
                    "troop_type_id": int(tt.id),
                    "code": tt.code,
                    "name": tt.name,
                    "tier": int(tt.tier),
                    "start": start,
                    "lost": lost,
                    "remaining": remaining,
                    "stats": {
                        "attack": int(tt.attack),
                        "defense": int(tt.defense),
                        "hp": int(tt.hp),
                        "speed": int(tt.speed),
                        "carry": int(tt.carry),
                    },
                }
            )
    else:
        # If raid has already hit combat phase, snapshot MUST exist.
        if raid.status in ("returning", "resolved"):
            # choose one behavior: error OR mark missing_snapshot
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "missing_defender_snapshot",
                    "message": "Raid is in combat phase but no defender snapshot exists.",
                    "raid_id": raid.id,
                    "status": raid.status,
                },
            )

        # Otherwise: still enroute — safe fallback (pre-impact)
        defender_source = "city_troops"
        defender_note = (
            "No per-raid defender snapshot exists yet. "
            "Showing current defender troops (pre-impact)."
        )

        if target:
            def_rows = (
                db.query(CityTroop, TroopType)
                .join(TroopType, TroopType.id == CityTroop.troop_type_id)
                .filter(CityTroop.city_id == target.id)
                .order_by(TroopType.id.asc())
                .all()
            )
            for ct, tt in def_rows:
                count = int(getattr(ct, "count", 0) or 0)
                defender_troops.append(
                    {
                        "troop_type_id": int(tt.id),
                        "code": tt.code,
                        "name": tt.name,
                        "tier": int(tt.tier),
                        "start": count,
                        "lost": 0,
                        "remaining": count,
                        "stats": {
                            "attack": int(tt.attack),
                            "defense": int(tt.defense),
                            "hp": int(tt.hp),
                            "speed": int(tt.speed),
                            "carry": int(tt.carry),
                        },
                    }
                )

    defender_totals: dict[str, int | float] = {
        "start": sum(int(t.get("start", 0) or 0) for t in defender_troops),
        "lost": sum(int(t.get("lost", 0) or 0) for t in defender_troops),
        "remaining": sum(int(t.get("remaining", 0) or 0) for t in defender_troops),
    }

    # -----------------------------
    # Combat power summary + damage breakdown
    # -----------------------------
    attacker_power_start = 0.0
    attacker_power_lost = 0.0
    attacker_damage_breakdown: list[dict] = []

    for t in attacker_troops:
        unit_power = float(t["stats"]["attack"]) + 0.10 * float(t["stats"]["hp"])
        sent = int(t["sent"])
        lost = int(t["lost"])
        returning = int(t["returning"])

        power_start = sent * unit_power
        power_lost = lost * unit_power
        power_remaining = returning * unit_power

        attacker_power_start += power_start
        attacker_power_lost += power_lost

        attacker_damage_breakdown.append(
            {
                "troop_type_id": int(t["troop_type_id"]),
                "code": t["code"],
                "name": t["name"],
                "sent": sent,
                "lost": lost,
                "returning": returning,
                "loss_pct": _loss_pct(lost, sent),
                "unit_power": _round2(unit_power),
                "power": {
                    "start": _round2(power_start),
                    "lost": _round2(power_lost),
                    "remaining": _round2(power_remaining),
                },
            }
        )

    defender_power_start = 0.0
    defender_power_lost = 0.0
    defender_damage_breakdown: list[dict] = []

    # only meaningful when we have snapshot rows (post-impact deterministic)
    has_snapshot = bool(snap_rows)

    if has_snapshot:
        for t in defender_troops:
            unit_power = float(t["stats"]["defense"]) + 0.10 * float(t["stats"]["hp"])
            start = int(t["start"])
            lost = int(t["lost"])
            remaining = int(t["remaining"])

            power_start = start * unit_power
            power_lost = lost * unit_power
            power_remaining = remaining * unit_power

            defender_power_start += power_start
            defender_power_lost += power_lost

            defender_damage_breakdown.append(
                {
                    "troop_type_id": int(t["troop_type_id"]),
                    "code": t["code"],
                    "name": t["name"],
                    "start": start,
                    "lost": lost,
                    "remaining": remaining,
                    "loss_pct": _loss_pct(lost, start),
                    "unit_power": _round2(unit_power),
                    "power": {
                        "start": _round2(power_start),
                        "lost": _round2(power_lost),
                        "remaining": _round2(power_remaining),
                    },
                }
            )

    if sort_damage_by_power_lost:
        attacker_damage_breakdown.sort(key=lambda r: r["power"]["lost"], reverse=True)
        if has_snapshot:
            defender_damage_breakdown.sort(key=lambda r: r["power"]["lost"], reverse=True)

    expected = None
    if attacker_power_start > 0 and defender_power_start > 0:
        ratio = defender_power_start / (attacker_power_start + defender_power_start)  # 0..1
        attacker_loss_rate = min(0.60, max(0.05, ratio * 0.80))
        defender_loss_rate = min(0.75, max(0.10, (1.0 - ratio) * 1.00))
        expected = {
            "ratio": _round2(ratio),
            "attacker_loss_rate": _round2(attacker_loss_rate),
            "defender_loss_rate": _round2(defender_loss_rate),
        }

    outcome_hint = None
    if include_outcome_hint and expected:
        # smaller ratio => attacker power share larger
        outcome_hint = "attacker_advantage" if float(expected["ratio"]) < 0.5 else "defender_advantage"

    combat_power_summary: dict[str, Any] = {
        "attacker": {
            "power_start": _round2(attacker_power_start),
            "power_lost": _round2(attacker_power_lost),
            "power_remaining": _round2(attacker_power_start - attacker_power_lost),
        },
        "defender": (
            None
            if not has_snapshot
            else {
                "power_start": _round2(defender_power_start),
                "power_lost": _round2(defender_power_lost),
                "power_remaining": _round2(defender_power_start - defender_power_lost),
            }
        ),
        "expected_rates": expected,
        "outcome_hint": outcome_hint,
        "notes": [
            "Power is reconstructed at report time using the same weights as tick.py.",
            "Expected rates are derived from total power ratio; per-type rounding can cause drift.",
        ],
    }

    # Optional tweak: add power totals into main blocks (handy for UI)
    if include_power_totals_in_main_blocks:
        atk_totals["power_start"] = _round2(attacker_power_start)
        atk_totals["power_lost"] = _round2(attacker_power_lost)
        atk_totals["power_remaining"] = _round2(attacker_power_start - attacker_power_lost)
        if has_snapshot:
            defender_totals["power_start"] = _round2(defender_power_start)
            defender_totals["power_lost"] = _round2(defender_power_lost)
            defender_totals["power_remaining"] = _round2(defender_power_start - defender_power_lost)

    return {
        "at": now.isoformat(),
        "raid": {
            "raid_id": raid.id,
            "status": raid.status,
            "attacker_city_id": raid.attacker_city_id,
            "target_city_id": raid.target_city_id,
            "carry_capacity": int(getattr(raid, "carry_capacity", 0) or 0),
            "created_at": raid.created_at.isoformat() if raid.created_at else None,
            "arrives_at": raid.arrives_at.isoformat() if raid.arrives_at else None,
            "returns_at": raid.returns_at.isoformat() if raid.returns_at else None,
            "resolved_at": raid.resolved_at.isoformat() if raid.resolved_at else None,
            "outbound_seconds": int(getattr(raid, "outbound_seconds", 0) or 0),
            "return_seconds": int(getattr(raid, "return_seconds", 0) or 0),
            "time_remaining_seconds": _time_remaining_seconds(now, raid),
        },
        "loot": {
            "food": int(getattr(raid, "stolen_food", 0) or 0),
            "wood": int(getattr(raid, "stolen_wood", 0) or 0),
            "stone": int(getattr(raid, "stolen_stone", 0) or 0),
            "iron": int(getattr(raid, "stolen_iron", 0) or 0),
        },
        "attacker": {
            "city_id": attacker.id if attacker else raid.attacker_city_id,
            "name": attacker.name if attacker else None,
            "troops": attacker_troops,
            "totals": atk_totals,
        },
        "defender": {
            "city_id": target.id if target else raid.target_city_id,
            "name": target.name if target else None,
            "source": defender_source,
            "troops": defender_troops,
            "totals": defender_totals,
            "note": defender_note,
        },
        "combat": {
            "power_summary": combat_power_summary,
            "damage_breakdown": {
                "attacker": attacker_damage_breakdown,
                "defender": None if not has_snapshot else defender_damage_breakdown,
                "note": None if has_snapshot else "No defender snapshot available; defender damage breakdown omitted.",
            },
        },
    }

@router.get("/{raid_id}/report")
def get_combat_report(
    raid_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    return _build_combat_report(
        raid_id=raid_id,
        db=db,
        current_user=current_user,
        x_admin_key=x_admin_key,
        include_power_totals_in_main_blocks=True,
        sort_damage_by_power_lost=True,
        include_outcome_hint=True,
    )

@router.get("/{raid_id}/report.html", response_class=HTMLResponse)
def get_combat_report_html(
    raid_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> HTMLResponse:
    rpt = _build_combat_report(
        raid_id=raid_id,
        db=db,
        current_user=current_user,
        x_admin_key=x_admin_key,
        include_power_totals_in_main_blocks=True,
        sort_damage_by_power_lost=True,
        include_outcome_hint=True,
    )

    raid = rpt["raid"]
    attacker = rpt["attacker"]
    defender = rpt["defender"]
    combat = rpt.get("combat", {})
    ps = combat.get("power_summary", {})
    dmg = combat.get("damage_breakdown", {}) or {}

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    def pretty(obj: Any) -> str:
        # pretty JSON for dict/list, else plain string
        if isinstance(obj, (dict, list)):
            return json.dumps(obj, indent=2, sort_keys=True)
        return str(obj)

    def render_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
        # cols: [(header, keypath)] where keypath can include dots
        def getv(row: dict, keypath: str):
            cur: Any = row
            for part in keypath.split("."):
                if not isinstance(cur, dict):
                    return ""
                cur = cur.get(part)
            return cur

        th = "".join(f"<th>{esc(h)}</th>" for h, _ in cols)
        trs = []
        for r in rows:
            tds = "".join(f"<td>{esc(getv(r, kp))}</td>" for _, kp in cols)
            trs.append(f"<tr>{tds}</tr>")
        return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(trs)}</tbody></table>"

    attacker_rows = attacker.get("troops", []) or []
    defender_rows = defender.get("troops", []) or []

    attacker_cols = [
        ("Type", "name"),
        ("Code", "code"),
        ("Sent", "sent"),
        ("Lost", "lost"),
        ("Returning", "returning"),
    ]
    defender_cols = [
        ("Type", "name"),
        ("Code", "code"),
        ("Start", "start"),
        ("Lost", "lost"),
        ("Remaining", "remaining"),
    ]

    atk_db = dmg.get("attacker") or []
    def_db = dmg.get("defender") or []

    atk_db_cols = [
        ("Type", "name"),
        ("Sent", "sent"),
        ("Lost", "lost"),
        ("Loss %", "loss_pct"),
        ("Unit Power", "unit_power"),
        ("Power Lost", "power.lost"),
    ]
    def_db_cols = [
        ("Type", "name"),
        ("Start", "start"),
        ("Lost", "lost"),
        ("Loss %", "loss_pct"),
        ("Unit Power", "unit_power"),
        ("Power Lost", "power.lost"),
    ]

    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Combat Report #{esc(raid.get("raid_id"))}</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 16px; }}
    .row {{ display: flex; gap: 16px; flex-wrap: wrap; }}
    .card {{ border: 1px solid #ddd; border-radius: 10px; padding: 12px; min-width: 320px; flex: 1; }}
    h1,h2,h3 {{ margin: 0 0 8px 0; }}
    .muted {{ color: #666; font-size: 13px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 6px 8px; text-align: left; font-size: 14px; }}
    th {{ background: #fafafa; }}
    code {{ background: #f6f6f6; padding: 2px 6px; border-radius: 6px; }}
    pre {{ background: #f6f6f6; padding: 10px; border-radius: 10px; overflow-x: auto; }}
    a {{ color: inherit; }}
  </style>
</head>
<body>
  <h1>Combat Report <code>#{esc(raid.get("raid_id"))}</code></h1>
  <div class="muted">
    Status: <b>{esc(raid.get("status"))}</b>
    • At: {esc(rpt.get("at"))}
    • Defender source: <b>{esc(defender.get("source"))}</b>
    • <a href="/raids/{esc(raid.get("raid_id"))}/report">View JSON</a>
  </div>

  <div class="row" style="margin-top: 12px;">
    <div class="card">
      <h2>Power Summary</h2>
      <div class="muted">Outcome hint: <b>{esc(ps.get("outcome_hint"))}</b></div>
      <pre>{esc(pretty(ps))}</pre>
    </div>

    <div class="card">
      <h2>Loot + Times</h2>
      <h3>Loot</h3>
      <pre>{esc(pretty(rpt.get("loot")))}</pre>
      <h3>Times</h3>
      <div class="muted">Arrives: {esc(raid.get("arrives_at"))}</div>
      <div class="muted">Returns: {esc(raid.get("returns_at"))}</div>
      <div class="muted">Resolved: {esc(raid.get("resolved_at"))}</div>
    </div>
  </div>

  <div class="row" style="margin-top: 12px;">
    <div class="card">
      <h2>Attacker: {esc(attacker.get("name"))} (City {esc(attacker.get("city_id"))})</h2>
      <div class="muted">Totals</div>
      <pre>{esc(pretty(attacker.get("totals")))}</pre>
      {render_table(attacker_rows, attacker_cols)}
    </div>

    <div class="card">
      <h2>Defender: {esc(defender.get("name"))} (City {esc(defender.get("city_id"))})</h2>
      <div class="muted">Totals</div>
      <pre>{esc(pretty(defender.get("totals")))}</pre>
      <div class="muted">{esc(defender.get("note"))}</div>
      {render_table(defender_rows, defender_cols)}
    </div>
  </div>

  <div class="row" style="margin-top: 12px;">
    <div class="card">
      <h2>Damage Breakdown (Attacker)</h2>
      {render_table(atk_db, atk_db_cols)}
    </div>

    <div class="card">
      <h2>Damage Breakdown (Defender)</h2>
      {("<div class='muted'>No defender snapshot available.</div>" if not def_db else render_table(def_db, def_db_cols))}
    </div>
  </div>

</body>
</html>
"""
    return HTMLResponse(content=html_out, status_code=200)

@router.get("/{raid_id}")
def get_raid(
    raid_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    now = tick_world_now(db)

    is_admin = _is_admin(x_admin_key)

    q = db.query(Raid).filter(Raid.id == raid_id)

    if not is_admin:
        q = (
            q.join(City, City.id == Raid.attacker_city_id)
             .filter(City.owner_id == current_user.id)
        )

    raid = q.first()
    if not raid:
        raise HTTPException(status_code=404, detail="Raid not found")

    return {
        "raid_id": raid.id,
        "report_url": f"/raids/{raid.id}/report.html",
        "report_json_url": f"/raids/{raid.id}/report",
        "status": raid.status,
        "attacker_city_id": raid.attacker_city_id,
        "target_city_id": raid.target_city_id,
        "carry_capacity": raid.carry_capacity,
        "created_at": raid.created_at.isoformat() if raid.created_at else None,
        "arrives_at": raid.arrives_at.isoformat() if raid.arrives_at else None,
        "returns_at": raid.returns_at.isoformat() if raid.returns_at else None,
        "resolved_at": raid.resolved_at.isoformat() if raid.resolved_at else None,
        "time_remaining_seconds": _time_remaining_seconds(now, raid),
        "stolen": {
            "food": raid.stolen_food,
            "wood": raid.stolen_wood,
            "stone": raid.stolen_stone,
            "iron": raid.stolen_iron,
        },
    }

