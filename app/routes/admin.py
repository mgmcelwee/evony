#app/routes/admin.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Body

from sqlalchemy.orm import Session

from pydantic import BaseModel, Field

from app.config import ADMIN_KEY
from app.database import get_db
from app.routes.auth import get_current_user

from app.models.city import City
from app.models.research import Research
from app.models.city_troop import CityTroop
from app.models.troop_type import TroopType
from app.models.hero import Hero

from app.game.research_rules import RESEARCH
from app.routes.research import ResearchSetRequest
from app.routes.cities import TroopsSetPayload
from app.routes.training import (
    TrainPayload,
    _training_rules_from_buildings,
    _compute_training_cost,
    _apply_cost_multiplier,
    _sum_cost,
    _check_affordable,
)
from app.routes.tick_util import tick_world_now

router = APIRouter(
    prefix="/admin",
    tags=["admin"]
)

class HeroSetRequest(BaseModel):
    name: str = Field(default="Roland", min_length=2, max_length=50)
    level: int = Field(default=1, ge=1, le=100)
    xp: int = Field(default=0, ge=0)
    attack_bonus: int = Field(default=0, ge=0)
    defense_bonus: int = Field(default=0, ge=0)
    march_speed_bonus: int = Field(default=0, ge=0)
    training_speed_bonus: int = Field(default=0, ge=0)
    research_speed_bonus: int = Field(default=0, ge=0)
    status: str = Field(default="idle")
    governor_research_speed_bonus: int = Field(default=0, ge=0)
    governor_training_speed_bonus: int = Field(default=0, ge=0)
    governor_production_bonus: int = Field(default=0, ge=0)


class HeroUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=50)
    level: int | None = Field(default=None, ge=1, le=100)
    xp: int | None = Field(default=None, ge=0)
    attack_bonus: int | None = Field(default=None, ge=0)
    defense_bonus: int | None = Field(default=None, ge=0)
    march_speed_bonus: int | None = Field(default=None, ge=0)
    training_speed_bonus: int | None = Field(default=None, ge=0)
    research_speed_bonus: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None)
    governor_research_speed_bonus: int | None = Field(default=None, ge=0)
    governor_training_speed_bonus: int | None = Field(default=None, ge=0)
    governor_production_bonus: int | None = Field(default=None, ge=0)

class HeroRenameRequest(BaseModel):
    name: str = Field(default="Roland", min_length=2, max_length=50)

def _is_admin(x_admin_key: str | None) -> bool:
    return bool(x_admin_key and x_admin_key == ADMIN_KEY)

def require_admin_key(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    if not x_admin_key or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin key required")
    return True

def _hero_to_dict(hero: Hero) -> dict:
    return {
        "id": int(hero.id),
        "city_id": int(hero.city_id),
        "name": hero.name,
        "level": int(hero.level),
        "xp": int(hero.xp),
        "status": hero.status,
        "bonuses": {
            "attack": int(hero.attack_bonus),
            "defense": int(hero.defense_bonus),
            "march_speed": int(hero.march_speed_bonus),
            "training_speed": int(hero.training_speed_bonus),
            "research_speed": int(hero.research_speed_bonus),
        },
        "governor_bonuses": {
            "research_speed": int(hero.governor_research_speed_bonus),
            "training_speed": int(hero.governor_training_speed_bonus),
            "production": int(hero.governor_production_bonus),
        },    
}

@router.post("/cities/{city_id}/research/set")
def admin_set_research_level(
    city_id: int,
    payload: ResearchSetRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not x_admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")

    _get_city_or_404(db, city_id, current_user, x_admin_key)

    key = payload.research_key.strip().lower()

    if key not in RESEARCH:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Research not found",
                "requested": payload.research_key,
                "available": sorted(RESEARCH.keys()),
            },
        )

    row = (
        db.query(Research)
        .filter(
            Research.city_id == city_id,
            Research.research_key == key,
        )
        .first()
    )

    if not row:
        row = Research(
            city_id=city_id,
            research_key=key,
            level=payload.level,
        )
        db.add(row)
    else:
        row.level = payload.level

    db.commit()

    return {
        "ok": True,
        "city_id": city_id,
        "research_key": key,
        "research_name": RESEARCH[key].display_name,
        "level": payload.level,
    }

@router.post("/cities/{city_id}/train/set")
def train_troops(
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

    # compute total cost
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

    # subtract resources
    city.food = int(getattr(city, "food", 0) or 0) - int(total_cost["food"])
    city.wood = int(getattr(city, "wood", 0) or 0) - int(total_cost["wood"])
    city.stone = int(getattr(city, "stone", 0) or 0) - int(total_cost["stone"])
    city.iron = int(getattr(city, "iron", 0) or 0) - int(total_cost["iron"])

    # apply troop increases
    updated = []
    for code, cnt in want_by_code.items():
        tt = by_code[code]
        row = (
            db.query(CityTroop)
            .filter(CityTroop.city_id == int(city.id), CityTroop.troop_type_id == int(tt.id))
            .first()
        )
        before = int(getattr(row, "count", 0) or 0) if row else 0
        if not row:
            row = CityTroop(city_id=int(city.id), troop_type_id=int(tt.id), count=0)
            db.add(row)
            db.flush()
        row.count = int(before) + int(cnt)
        updated.append({"code": code, "before": int(before), "after": int(row.count), "added": int(cnt)})

    db.commit()
    db.refresh(city)

    return {
        "ok": True,
        "city_id": int(city.id),
        "rules": rules,
        "total_units": int(total_units),
        "trained": breakdown,
        "total_cost": total_cost,
        "resources_after": {
            "food": int(city.food),
            "wood": int(city.wood),
            "stone": int(city.stone),
            "iron": int(city.iron),
        },
        "updated": updated,
    }

@router.post("/cities/{city_id}/troops/set")
def admin_set_city_troops(
    city_id: int,
    payload: TroopsSetPayload = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    troops = [t.model_dump() for t in payload.troops]
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

@router.post("/cities/{city_id}/heroes/set")
def admin_set_hero(
    city_id: int,
    payload: HeroSetRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    city = db.query(City).filter(City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    hero = Hero(
        city_id=city_id,
        name=payload.name.strip(),
        level=payload.level,
        xp=payload.xp,
        attack_bonus=payload.attack_bonus,
        defense_bonus=payload.defense_bonus,
        march_speed_bonus=payload.march_speed_bonus,
        training_speed_bonus=payload.training_speed_bonus,
        research_speed_bonus=payload.research_speed_bonus,
        governor_research_speed_bonus=payload.governor_research_speed_bonus,
        governor_training_speed_bonus=payload.governor_training_speed_bonus,
        governor_production_bonus=payload.governor_production_bonus,
        status=payload.status.strip(),
    )

    db.add(hero)
    db.commit()
    db.refresh(hero)

    return {
        "ok": True,
        "city_id": city_id,
        "hero": _hero_to_dict(hero),
    }

@router.get("/heroes/{hero_id}")
def admin_get_hero(
    hero_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    return {"ok": True, "hero": _hero_to_dict(hero)}


@router.post("/heroes/{hero_id}/set")
def admin_update_hero(
    hero_id: int,
    payload: HeroUpdateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    data = payload.model_dump(exclude_unset=True)

    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(hero, field, value)

    db.commit()
    db.refresh(hero)

    return {"ok": True, "hero": _hero_to_dict(hero)}


@router.post("/heroes/{hero_id}/rename")
def admin_rename_hero(
    hero_id: int,
    payload: HeroRenameRequest = Body(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    hero.name = payload.name.strip()
    db.commit()
    db.refresh(hero)

    return {"ok": True, "hero": _hero_to_dict(hero)}


@router.delete("/heroes/{hero_id}")
def admin_delete_hero(
    hero_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    if not _is_admin(x_admin_key):
        raise HTTPException(status_code=403, detail="Forbidden")

    hero = db.query(Hero).filter(Hero.id == hero_id).first()
    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    deleted = _hero_to_dict(hero)

    db.delete(hero)
    db.commit()

    return {
        "ok": True,
        "deleted": deleted,
    }
