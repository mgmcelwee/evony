from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.hero import Hero
from app.routes.auth import get_current_user
from app.routes.buildings import _get_city_or_404


router = APIRouter(
    prefix="/cities",
    tags=["heroes"],
)

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
    }

class HeroCreateRequest(BaseModel):
    name: str = Field(default="Roland", min_length=2, max_length=50)


@router.get("/{city_id}/heroes")
def list_heroes(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    rows = db.query(Hero).filter(Hero.city_id == int(city.id)).order_by(Hero.id.asc()).all()

    return {
        "ok": True,
        "city_id": int(city.id),
        "count": len(rows),
        "heroes": [
            {
                "id": int(h.id),
                "name": h.name,
                "level": int(h.level),
                "xp": int(h.xp),
                "status": h.status,
                "bonuses": {
                    "attack": int(h.attack_bonus),
                    "defense": int(h.defense_bonus),
                    "march_speed": int(h.march_speed_bonus),
                    "training_speed": int(h.training_speed_bonus),
                    "research_speed": int(h.research_speed_bonus),
                },
            }
            for h in rows
        ],
    }


@router.post("/{city_id}/heroes")
def create_hero(
    city_id: int,
    payload: HeroCreateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    hero = Hero(
        city_id=int(city.id),
        name=payload.name.strip(),
    )

    db.add(hero)
    db.commit()
    db.refresh(hero)

    return {
        "ok": True,
        "city_id": int(city.id),
        "hero": {
            "id": int(hero.id),
            "name": hero.name,
            "level": int(hero.level),
            "xp": int(hero.xp),
            "status": hero.status,
        },
    }

@router.post("/{city_id}/heroes/{hero_id}/governor")
def assign_governor(
    city_id: int,
    hero_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    hero = (
        db.query(Hero)
        .filter(
            Hero.id == hero_id,
            Hero.city_id == city.id,
        )
        .first()
    )

    if not hero:
        raise HTTPException(status_code=404, detail="Hero not found")

    # Remove existing governor
    (
        db.query(Hero)
        .filter(
            Hero.city_id == city.id,
            Hero.status == "governor",
        )
        .update({"status": "idle"})
    )

    hero.status = "governor"

    db.commit()
    db.refresh(hero)

    return {
        "ok": True,
        "city_id": city.id,
        "governor": {
            "id": hero.id,
            "name": hero.name,
            "status": hero.status,
        },
    }

@router.get("/{city_id}/governor")
def get_governor(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    hero = (
        db.query(Hero)
        .filter(
            Hero.city_id == city.id,
            Hero.status == "governor",
        )
        .first()
    )

    return {
        "city_id": city.id,
        "governor": _hero_to_dict(hero) if hero else None,
    }

@router.delete("/{city_id}/governor")
def remove_governor(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    hero = (
        db.query(Hero)
        .filter(
            Hero.city_id == city.id,
            Hero.status == "governor",
        )
        .first()
    )

    if hero:
        hero.status = "idle"
        db.commit()

    return {"ok": True}


