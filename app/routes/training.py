# app/routes/training.py
from __future__ import annotations

import math
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Body, Query
from sqlalchemy.orm import Session
from sqlalchemy import update
from pydantic import BaseModel, Field

from app.config import ADMIN_KEY
from app.database import get_db
from app.models.city import City
from app.routes.auth import get_current_user
from app.routes.tick_util import tick_world_now
from app.models.city_troop import CityTroop
from app.models.troop_type import TroopType
from app.models.building import Building
from app.models.training_queue import TrainingQueue
from app.game.governor import get_city_governor_bonus
from app.game.tick import _recalc_storage_for_city

router = APIRouter(prefix="/cities", tags=["training"])


class TrainRequest(BaseModel):
    troop_code: str
    count: int

class TrainQueueRequest(BaseModel):
    troops: list[TroopLine] = Field(
        default_factory=lambda: [TroopLine()]
    )

class TrainTroopLine(BaseModel):
    code: str = Field(default="t1_inf", min_length=1, max_length=32)
    count: int = Field(default=10, ge=1)

class TrainPayload(BaseModel):
    troops: list[TrainTroopLine] = Field(
        default_factory=lambda: [TrainTroopLine()]
    )

def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)

# --- Training (v1: instant) ------------------------------------
def _get_city_or_404(
    db: Session,
    city_id: int,
    current_user,
    x_admin_key: str | None,
) -> City:
    q = db.query(City).filter(City.id == int(city_id))
    if not _is_admin(x_admin_key):
        q = q.filter(City.owner_id == current_user.id)
    city = q.first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    return city

def _compute_training_cost(tt: TroopType, count: int) -> dict:
    """
    Simple v1 costs. Tweak freely.
    Uses tier to scale so T1 is cheap.
    """
    tier = int(getattr(tt, "tier", 1) or 1)
    count = max(0, int(count))

    # Per-unit costs by tier (v1)
    # T1: 1 food, 1 wood
    # T2: 2 food, 2 wood, 1 stone
    # T3+: add iron too
    food_u = 1 * tier
    wood_u = 1 * tier
    stone_u = 0 if tier <= 1 else (tier - 1)
    iron_u = 0 if tier <= 2 else (tier - 2)

    return {
        "food": int(food_u * count),
        "wood": int(wood_u * count),
        "stone": int(stone_u * count),
        "iron": int(iron_u * count),
    }

def _barracks_level(db: Session, city_id: int) -> int:
    row = (
        db.query(Building)
        .filter(Building.city_id == int(city_id), Building.type == "barracks")
        .first()
    )
    return int(getattr(row, "level", 1) or 1)

def _training_rules_from_buildings(db: Session, city_id: int) -> dict:
    """
    v1 building effects:
      - Barracks level increases max batch size
      - Barracks level reduces resource cost (discount)
    """
    lvl = _barracks_level(db, city_id)

    # Batch cap curve (tune freely)
    # L1=25, L2=50, L3=75, ...
    max_batch = max(1, 25 * int(lvl))

    # Discount curve: 0% at L1, -5% per level, floor at 50% cost
    # L1=1.00, L2=0.95, L3=0.90, ... floor=0.50
    cost_mult = max(0.50, 1.0 - 0.05 * (lvl - 1))

    # Add queue slots
    queue_slots = max(1, int(lvl))

    return {
        "barracks_level": int(lvl),
        "max_batch": int(max_batch),
        "cost_multiplier": float(round(cost_mult, 4)),
        "queue_slots": int(queue_slots), 
        }

def _apply_cost_multiplier(cost: dict, mult: float) -> dict:
    import math
    mult = float(mult or 1.0)
    out = {}
    for k, v in cost.items():
        v = int(v or 0)
        scaled = int(math.floor(v * mult + 1e-9))
        out[k] = max(0, scaled)
    return out

def _sum_cost(costs: list[dict]) -> dict:
    out = {"food": 0, "wood": 0, "stone": 0, "iron": 0}
    for c in costs:
        for k in out.keys():
            out[k] += int(c.get(k, 0) or 0)
    return out


def _check_affordable(city: City, cost: dict) -> dict:
    have = {
        "food": int(getattr(city, "food", 0) or 0),
        "wood": int(getattr(city, "wood", 0) or 0),
        "stone": int(getattr(city, "stone", 0) or 0),
        "iron": int(getattr(city, "iron", 0) or 0),
    }
    missing = {}
    for k, v in cost.items():
        if have[k] < int(v):
            missing[k] = int(v) - have[k]
    return {"ok": (len(missing) == 0), "have": have, "missing": missing}

def _get_city_training_bonus(db: Session, city_id: int) -> dict:
    governor, bonuses = get_city_governor_bonus(db, int(city_id))

    bonus = int(bonuses.get("training_speed_bonus", 0) * 100)
    bonus = max(0, min(bonus, 90))

    return {
        "governor": governor,
        "bonus": bonus,
    }

def seconds_for(tt: TroopType, count: int, barracks_level: int, governor_bonus: int = 0) -> int:
    tier = int(getattr(tt, "tier", 1) or 1)
    sec_per_unit = 1 + tier
    barracks_mult = max(0.50, 1.0 - 0.03 * (max(1, int(barracks_level)) - 1))
    governor_mult = max(0.10, (100 - int(governor_bonus)) / 100.0)
    seconds = int(math.ceil(float(sec_per_unit) * int(count) * float(barracks_mult) * float(governor_mult)))
    return max(1, seconds)

@router.post("/{city_id}/train/preview")
def train_preview(
    city_id: int,
    payload: TrainPayload = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    tick_world_now(db)

    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    troops = [t.model_dump() for t in payload.troops]
    if not isinstance(troops, list) or not troops:
        raise HTTPException(status_code=400, detail="troops list required")

    # normalize + aggregate by code
    want_by_code: dict[str, int] = {}
    for t in troops:
        code = str(t.get("code", "")).strip()
        cnt = int(t.get("count", 0) or 0)
        if not code or cnt <= 0:
            raise HTTPException(status_code=400, detail="Invalid troop line")
        want_by_code[code] = want_by_code.get(code, 0) + cnt

    # --- Buildings affect training (Barracks rules) ---
    rules = _training_rules_from_buildings(db, int(city.id))
    total_units = sum(int(v) for v in want_by_code.values())
    if total_units > int(rules["max_batch"]):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Training batch too large",
                "total_units": int(total_units),
                "max_batch": int(rules["max_batch"]),
                "barracks_level": int(rules.get("barracks_level", 0) or 0),
            },
        )

    types = db.query(TroopType).filter(TroopType.code.in_(list(want_by_code.keys()))).all()
    by_code = {tt.code: tt for tt in types}

    missing_codes = [c for c in want_by_code.keys() if c not in by_code]
    if missing_codes:
        raise HTTPException(status_code=400, detail={"error": "Unknown troop code(s)", "codes": missing_codes})

    breakdown = []
    costs = []
    for code, cnt in want_by_code.items():
        tt = by_code[code]
        base_cost = _compute_training_cost(tt, cnt)
        cost = _apply_cost_multiplier(base_cost, rules["cost_multiplier"])
        costs.append(cost)
        breakdown.append(
            {
                "code": code,
                "name": tt.name,
                "tier": int(getattr(tt, "tier", 0) or 0),
                "count": int(cnt),
                "cost": cost,
            }
        )

    total_cost = _sum_cost(costs)
    afford = _check_affordable(city, total_cost)
    governor, bonuses = get_city_governor_bonus(db, int(city.id))
    governor_training_bonus = int(bonuses.get("training_speed_bonus", 0) * 100)
    governor_training_bonus = max(0, min(governor_training_bonus, 90))

    barracks_level = int(rules.get("barracks_level", 1) or 1)

    base_duration_seconds = 0
    duration_seconds = 0

    for code, cnt in want_by_code.items():
        tt = by_code[code]
        base_duration_seconds += seconds_for(tt, cnt, barracks_level, 0)
        duration_seconds += seconds_for(tt, cnt, barracks_level, governor_training_bonus)

    return {
        "ok": True,
        "city_id": int(city.id),
        "rules": rules,
        "total_units": int(total_units),
        "troops": breakdown,
        "total_cost": total_cost,
        "base_duration_seconds": int(base_duration_seconds),
        "duration_seconds": int(duration_seconds),
        "affordable": bool(afford["ok"]),
        "have": afford["have"],
        "missing": afford["missing"],
        "governor_bonus": {
            "hero_id": governor.id if governor else None,
            "name": governor.name if governor else None,
            "training_speed_bonus": governor_training_bonus,
        },
    }

@router.get("/{city_id}/train/queue")
def get_train_queue(
    city_id: int,
    status: str | None = Query(default="training"),    # optional filter
    before_id: int | None = Query(default=None),     # pagination cursor
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    tick_world_now(db)
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    q = (
        db.query(TrainingQueue, TroopType)
        .join(TroopType, TroopType.id == TrainingQueue.troop_type_id)
        .filter(TrainingQueue.city_id == int(city.id))
    )

    if status:
        q = q.filter(TrainingQueue.status == status)

    if before_id is not None:
        q = q.filter(TrainingQueue.id < int(before_id))

    # newest first (history)
    rows = (
        q.order_by(TrainingQueue.id.desc())
        .limit(int(limit) + 1)   # fetch one extra to detect next page
        .all()
    )

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = []
    for tq, tt in rows:
        items.append({
            "id": int(tq.id),
            "code": tt.code,
            "name": tt.name,
            "tier": int(getattr(tt, "tier", 0) or 0),
            "count": int(tq.count),
            "status": tq.status,
            "started_at": tq.started_at.isoformat(),
            "finishes_at": tq.finishes_at.isoformat(),
            "seconds_total": int(tq.seconds_total),
            "cost": {
                "food": int(tq.cost_food),
                "wood": int(tq.cost_wood),
                "stone": int(tq.cost_stone),
                "iron": int(tq.cost_iron),
            },
        })

    next_before_id = int(items[-1]["id"]) if (has_more and items) else None

    return {
        "ok": True,
        "city_id": int(city.id),
        "count": len(items),
        "next_before_id": next_before_id,
        "queue": items,
    }

@router.post("/{city_id}/train/queue/{queue_id}/cancel")
def cancel_train_queue(
    city_id: int,
    queue_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    tick_world_now(db)
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    now = datetime.utcnow()

    # Load row first for friendly errors + refund amounts
    tq = (
        db.query(TrainingQueue)
        .filter(TrainingQueue.id == int(queue_id), TrainingQueue.city_id == int(city.id))
        .first()
    )
    if not tq:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if tq.status != "training":
        raise HTTPException(status_code=409, detail={"error": "Not cancellable", "status": tq.status})

    if tq.finishes_at <= now:
        # it *should* have been finalized by tick_world_now, but keep it safe
        raise HTTPException(status_code=409, detail={"error": "Already finished", "finishes_at": tq.finishes_at.isoformat()})

    # Atomic claim: training -> cancelled
    res = db.execute(
        update(TrainingQueue)
        .where(
            TrainingQueue.id == int(queue_id),
            TrainingQueue.city_id == int(city.id),
            TrainingQueue.status == "training",
        )
        .values(status="cancelled")
    )
    if res.rowcount != 1:
        raise HTTPException(status_code=409, detail={"error": "Cancel race lost"})

    db.flush()

    # Refund (full refund of stored cost)
    refund = {
        "food": int(getattr(tq, "cost_food", 0) or 0),
        "wood": int(getattr(tq, "cost_wood", 0) or 0),
        "stone": int(getattr(tq, "cost_stone", 0) or 0),
        "iron": int(getattr(tq, "cost_iron", 0) or 0),
    }

    # clamp to storage after refund
    # (you already have _recalc_storage_for_city in tick.py; import it or duplicate storage calc here)
    # If you can import:
    # from app.game.tick import _recalc_storage_for_city
    s = _recalc_storage_for_city(db, int(city.id))
    city.max_food = s["max_food"]; city.max_wood = s["max_wood"]; city.max_stone = s["max_stone"]; city.max_iron = s["max_iron"]

    city.food = min(int(city.max_food), int(city.food) + refund["food"])
    city.wood = min(int(city.max_wood), int(city.wood) + refund["wood"])
    city.stone = min(int(city.max_stone), int(city.stone) + refund["stone"])
    city.iron = min(int(city.max_iron), int(city.iron) + refund["iron"])

    db.commit()
    db.refresh(city)

    return {
        "ok": True,
        "city_id": int(city.id),
        "queue_id": int(queue_id),
        "status": "cancelled",
        "refunded": refund,
        "resources_after": {
            "food": int(city.food),
            "wood": int(city.wood),
            "stone": int(city.stone),
            "iron": int(city.iron),
        },
    }

@router.post("/{city_id}/train/queue")
def train_queue(
    city_id: int,
    payload: TrainPayload = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    """
    Training v2: queue-based.
    - Charges resources immediately (deterministic cost stored on each queue row)
    - Troops are granted later by tick() when finishes_at <= now
    """
    tick_world_now(db)

    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    troops = [t.model_dump() for t in payload.troops]
    if not isinstance(troops, list) or not troops:
        raise HTTPException(status_code=400, detail="troops list required")

    # normalize + aggregate by code
    want_by_code: dict[str, int] = {}
    for t in troops:
        code = str(t.get("code", "")).strip()
        cnt = int(t.get("count", 0) or 0)
        if not code or cnt <= 0:
            raise HTTPException(status_code=400, detail="Invalid troop line")
        want_by_code[code] = want_by_code.get(code, 0) + cnt

    # building rules (reuse your existing barracks tuning)
    rules = _training_rules_from_buildings(db, int(city.id))
    total_units = sum(int(v) for v in want_by_code.values())
    if total_units > int(rules["max_batch"]):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Training batch too large",
                "total_units": int(total_units),
                "max_batch": int(rules["max_batch"]),
                "barracks_level": int(rules.get("barracks_level", 0) or 0),
            },
        )

    # ✅ Queue slot gating (before charging resources)
    active_count = (
        db.query(TrainingQueue)
        .filter(
            TrainingQueue.city_id == int(city.id),
            TrainingQueue.status.in_(["training", "processing"]),
        )
        .count()
    )

    slots_total = int(rules.get("queue_slots", 1) or 1)
    slots_free = max(0, slots_total - int(active_count))

    # how many rows will this request create?
    rows_needed = len(want_by_code)  # one row per troop code (after aggregation)

    if rows_needed > slots_free:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Training queue full",
                "slots_total": int(slots_total),
                "slots_used": int(active_count),
                "slots_free": int(slots_free),
                "rows_needed": int(rows_needed),
            },
        )

    # load troop types
    types = (
        db.query(TroopType)
        .filter(TroopType.code.in_(list(want_by_code.keys())))
        .all()
    )
    by_code = {tt.code: tt for tt in types}
    missing_codes = [c for c in want_by_code.keys() if c not in by_code]
    if missing_codes:
        raise HTTPException(status_code=400, detail={"error": "Unknown troop code(s)", "codes": missing_codes})

    now = datetime.utcnow()
    barracks_level = int(rules.get("barracks_level", 1) or 1)
    governor, bonuses = get_city_governor_bonus(db, int(city.id))
    governor_training_bonus = int(bonuses.get("training_speed_bonus", 0) * 100)
    governor_training_bonus = max(0, min(governor_training_bonus, 90))

    # compute costs + affordability (charge immediately)
    breakdown = []
    costs = []
    per_line_cost: dict[str, dict] = {}

    for code, cnt in want_by_code.items():
        tt = by_code[code]
        base_cost = _compute_training_cost(tt, cnt)
        cost = _apply_cost_multiplier(base_cost, rules["cost_multiplier"])
        per_line_cost[code] = cost
        costs.append(cost)

        breakdown.append(
            {
                "code": code,
                "name": tt.name,
                "tier": int(getattr(tt, "tier", 0) or 0),
                "count": int(cnt),
                "cost": cost,
            }
        )

    total_cost = _sum_cost(costs)
    afford = _check_affordable(city, total_cost)
    if not afford["ok"]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Insufficient resources",
                "cost": total_cost,
                "have": afford.get("have"),
                "missing": afford["missing"],
            },
        )

    # subtract resources NOW (so queue is deterministic)
    city.food = int(getattr(city, "food", 0) or 0) - int(total_cost["food"])
    city.wood = int(getattr(city, "wood", 0) or 0) - int(total_cost["wood"])
    city.stone = int(getattr(city, "stone", 0) or 0) - int(total_cost["stone"])
    city.iron = int(getattr(city, "iron", 0) or 0) - int(total_cost["iron"])

    # create queue rows
    base_duration_seconds = 0
    duration_seconds = 0
    queued = []

    for code, cnt in want_by_code.items():
        tt = by_code[code]

        base_seconds_total = seconds_for(tt, cnt, barracks_level, 0)
        seconds_total = seconds_for(tt, cnt, barracks_level, governor_training_bonus)

        base_duration_seconds += int(base_seconds_total)
        duration_seconds += int(seconds_total)

        finishes_at = now + timedelta(seconds=seconds_total)

        tq = TrainingQueue(
            city_id=int(city.id),
            troop_type_id=int(tt.id),
            count=int(cnt),
            status="training",
            started_at=now,
            finishes_at=finishes_at,
            seconds_total=int(seconds_total),
            cost_food=int(per_line_cost[code]["food"]),
            cost_wood=int(per_line_cost[code]["wood"]),
            cost_stone=int(per_line_cost[code]["stone"]),
            cost_iron=int(per_line_cost[code]["iron"]),
        )

        db.add(tq)
        db.flush()

        queued.append({
            "id": int(tq.id),
            "code": tt.code,
            "name": tt.name,
            "tier": int(getattr(tt, "tier", 0) or 0),
            "count": int(cnt),
            "status": tq.status,
            "started_at": tq.started_at.isoformat(),
            "finishes_at": tq.finishes_at.isoformat(),
            "base_seconds_total": int(base_seconds_total),
            "seconds_total": int(seconds_total),
            "cost": per_line_cost[code],
        })

    db.commit()
    db.refresh(city)

    return {
        "ok": True,
        "city_id": int(city.id),
        "rules": rules,
        "total_units": int(total_units),
        "queued": queued,
        "total_cost": total_cost,
	"base_duration_seconds": int(base_duration_seconds),
	"duration_seconds": int(duration_seconds),
	"resources_after": {
            "food": int(city.food),
            "wood": int(city.wood),
            "stone": int(city.stone),
            "iron": int(city.iron),
        },
        "slots": {
            "total": int(slots_total),
            "used": int(active_count) + len(queued),
            "free": max(0, int(slots_total) - (int(active_count) + len(queued))),
        },
        "note": "Troops will appear after finishes_at when a tick occurs (any tick-on-read endpoint).",
        "governor_bonus": {
            "hero_id": governor.id if governor else None,
            "name": governor.name if governor else None,
            "training_speed_bonus": governor_training_bonus,
        },
    }

