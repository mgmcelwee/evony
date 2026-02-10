# app/routes/cities.py
from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Body
from sqlalchemy.orm import Session

from app.config import ADMIN_KEY
from app.database import get_db
from app.models.city import City
from app.routes.auth import get_current_user
from app.routes.tick_util import tick_world_now
from app.models.city_troop import CityTroop
from app.models.troop_type import TroopType


router = APIRouter(prefix="/cities", tags=["cities"])



def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)

@router.get("/{city_id}")
def get_city(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    # Tick world before serving read response (throttled)
    tick_world_now(db)

    q = db.query(City).filter(City.id == city_id)
    if not _is_admin(x_admin_key):
        q = q.filter(City.owner_id == current_user.id)

    city = q.first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    return {
        "city_id": city.id,
        "name": city.name,
        "townhall_level": city.townhall_level,
        "resources": {
            "food": city.food,
            "wood": city.wood,
            "stone": city.stone,
            "iron": city.iron,
        },
        "rates_per_min": {
            "food_rate": city.food_rate,
            "wood_rate": city.wood_rate,
            "stone_rate": city.stone_rate,
            "iron_rate": city.iron_rate,
        },
        "caps": {
            "max_food": city.max_food,
            "max_wood": city.max_wood,
            "max_stone": city.max_stone,
            "max_iron": city.max_iron,
        },
        "protected": {
            "food": city.protected_food,
            "wood": city.protected_wood,
            "stone": city.protected_stone,
            "iron": city.protected_iron,
        },
        "lootable": {
            "food": max(0, city.food - city.protected_food),
            "wood": max(0, city.wood - city.protected_wood),
            "stone": max(0, city.stone - city.protected_stone),
            "iron": max(0, city.iron - city.protected_iron),
        },
        "last_tick_at": city.last_tick_at.isoformat() if city.last_tick_at else None,
    }

@router.get("/{city_id}/troops")
def get_city_troops(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    # Tick world before serving read response (throttled)
    tick_world_now(db)

    # City access control (same pattern as get_city)
    q = db.query(City).filter(City.id == city_id)
    if not _is_admin(x_admin_key):
        q = q.filter(City.owner_id == current_user.id)

    city = q.first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    rows = (
        db.query(CityTroop, TroopType)
        .join(TroopType, TroopType.id == CityTroop.troop_type_id)
        .filter(CityTroop.city_id == city_id)
        .order_by(TroopType.tier.asc(), TroopType.id.asc())
        .all()
    )

    troops = []
    total_units = 0
    total_carry = 0

    for ct, tt in rows:
        cnt = max(0, int(getattr(ct, "count", 0) or 0))
        total_units += cnt
        total_carry += cnt * max(0, int(getattr(tt, "carry", 0) or 0))

        troops.append(
            {
                "troop_type_id": int(tt.id),
                "code": tt.code,
                "name": tt.name,
                "tier": int(getattr(tt, "tier", 0) or 0),
                "count": cnt,
                "speed": int(getattr(tt, "speed", 0) or 0),
                "carry": int(getattr(tt, "carry", 0) or 0),
                "attack": int(getattr(tt, "attack", 0) or 0),
                "defense": int(getattr(tt, "defense", 0) or 0),
                "hp": int(getattr(tt, "hp", 0) or 0),
            }
        )

    return {
        "city_id": city.id,
        "name": city.name,
        "troops": troops,
        "totals": {
            "units": int(total_units),
            "carry": int(total_carry),
        },
        "at": datetime.utcnow().isoformat(),
    }

@router.post("/{city_id}/troops/set")
def admin_set_city_troops(
    city_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    troops = payload.get("troops") or []
    if not isinstance(troops, list) or not troops:
        raise HTTPException(status_code=400, detail="troops list required")

    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    codes = [str(t.get("code", "")).strip() for t in troops]
    types = db.query(TroopType).filter(TroopType.code.in_(codes)).all()
    by_code = {tt.code: tt for tt in types}

    updated = []
    for t in troops:
        code = str(t.get("code", "")).strip()
        cnt = int(t.get("count", 0) or 0)
        if code not in by_code:
            raise HTTPException(status_code=400, detail={"error": "Unknown troop code", "code": code})

        tt = by_code[code]
        row = (
            db.query(CityTroop)
            .filter(CityTroop.city_id == city_id, CityTroop.troop_type_id == tt.id)
            .first()
        )
        if not row:
            row = CityTroop(city_id=city_id, troop_type_id=tt.id, count=0)
            db.add(row)
            db.flush()

        row.count = max(0, cnt)
        updated.append({"code": code, "count": row.count})

    db.commit()
    return {"ok": True, "city_id": city_id, "updated": updated}
