# app/routes/cities.py
from __future__ import annotations

import os
import secrets
import math
from datetime import datetime, timedelta
from typing import Optional, Any

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
from app.game.tick import _recalc_storage_for_city

router = APIRouter(prefix="/cities", tags=["cities"])

class TroopLine(BaseModel):
    code: str = Field(default="t1_inf")
    count: int = Field(default=10)


class TroopsSetRequest(BaseModel):
    troops: list[TroopLine] = Field(
        default_factory=lambda: [TroopLine()]
    )

class ResearchRequest(BaseModel):
    research_key: str = Field(default="agriculture")

class TroopsSetPayload(BaseModel):
    troops: list[TroopLine] = Field(
        default_factory=lambda: [TroopLine()]
    )

TroopsSetPayload.model_rebuild()

class ResourceBlock(BaseModel):
    food: int = 0
    wood: int = 0
    stone: int = 0
    iron: int = 0


class RatesBlock(BaseModel):
    food_rate: int = 0
    wood_rate: int = 0
    stone_rate: int = 0
    iron_rate: int = 0


class CityResponse(BaseModel):
    city_id: int
    name: str
    townhall_level: int
    resources: ResourceBlock
    rates_per_min: RatesBlock
    caps: ResourceBlock
    protected: ResourceBlock
    lootable: ResourceBlock
    last_tick_at: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "city_id": 1,
                "name": "EvoCapital",
                "townhall_level": 1,
                "resources": {
                    "food": 0,
                    "wood": 0,
                    "stone": 0,
                    "iron": 0
                },
                "rates_per_min": {
                    "food_rate": 40,
                    "wood_rate": 30,
                    "stone_rate": 17,
                    "iron_rate": 9
                },
                "caps": {
                    "food": 1000,
                    "wood": 1000,
                    "stone": 1000,
                    "iron": 1000
                },
                "protected": {
                    "food": 0,
                    "wood": 0,
                    "stone": 0,
                    "iron": 0
                },
                "lootable": {
                    "food": 0,
                    "wood": 0,
                    "stone": 0,
                    "iron": 0
                },
                "last_tick_at": None
            }
        }
    }

class TroopView(BaseModel):
    troop_type_id: int = 1
    code: str = "t1_inf"
    name: str = "T1 Infantry"
    tier: int = 1
    count: int = 5
    speed: int = 100
    carry: int = 5
    attack: int = 10
    defense: int = 12
    hp: int = 120


class TroopTotals(BaseModel):
    units: int = 5
    carry: int = 25


class CityTroopsResponse(BaseModel):
    city_id: int = 1
    name: str = "EvoCapital"
    troops: list[TroopView] = Field(default_factory=lambda: [TroopView()])
    totals: TroopTotals = TroopTotals()
    at: str | None = None

def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)

@router.get("/{city_id}", response_model=CityResponse)
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

@router.get("/{city_id}/troops", response_model=CityTroopsResponse)
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

