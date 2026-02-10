# app/routes/buildings.py
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.city import City
from app.models.building import Building
from app.models.upgrade import Upgrade
from app.routes.auth import get_current_user

from app.game.building_rules import (
    normalize_building_type,
    display_building_type,
    accepted_display_types,
    upgrade_cost,
    upgrade_time_seconds,
    check_prereqs,
)

router = APIRouter(prefix="/cities", tags=["buildings"])

ADMIN_KEY = os.getenv("ADMIN_KEY", "")


def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)


def _get_city_or_404(
    db: Session,
    city_id: int,
    current_user,
    x_admin_key: str | None,
) -> City:
    q = db.query(City).filter(City.id == city_id)
    if not _is_admin(x_admin_key):
        q = q.filter(City.owner_id == current_user.id)

    city = q.first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")
    return city


class UpgradeRequest(BaseModel):
    building_type: str = Field(min_length=2, max_length=32)


@router.get("/{city_id}/buildings")
def list_buildings(
    city_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    # Ownership enforced unless admin
    _get_city_or_404(db, city_id, current_user, x_admin_key)

    buildings = db.query(Building).filter(Building.city_id == city_id).all()
    active = db.query(Upgrade).filter(Upgrade.city_id == city_id).first()

    return {
        "city_id": city_id,
        "buildings": [
            {"type": display_building_type(b.type), "level": b.level, "canonical_type": b.type}
            for b in buildings
        ],
        "active_upgrade": (
            {
                "building_type": display_building_type(active.building_type),
                "canonical_type": active.building_type,
                "from_level": active.from_level,
                "to_level": active.to_level,
                "started_at": active.started_at.isoformat(),
                "completes_at": active.completes_at.isoformat(),
            }
            if active
            else None
        ),
        "accepted_building_types": accepted_display_types(),
    }

@router.get("/{city_id}/upgrade/preview")
def preview_upgrade(
    city_id: int,
    building_type: str = Query(..., min_length=2, max_length=32),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    requested = building_type
    canonical = normalize_building_type(requested)

    # One builder rule
    existing = db.query(Upgrade).filter(Upgrade.city_id == city_id).first()
    if existing:
        return {
            "allowed": False,
            "error": "Upgrade already in progress",
            "active": {
                "building_type": display_building_type(existing.building_type),
                "canonical_type": existing.building_type,
                "from_level": existing.from_level,
                "to_level": existing.to_level,
                "completes_at": existing.completes_at.isoformat(),
            },
        }

    # Pull all buildings once (reuse for levels + lookup)
    city_buildings = db.query(Building).filter(Building.city_id == city_id).all()
    levels = {cb.type: cb.level for cb in city_buildings}

    b = next((cb for cb in city_buildings if cb.type == canonical), None)
    if not b:
        return {
            "allowed": False,
            "error": "Building not found",
            "requested": requested,
            "canonical": canonical,
            "available_in_city": sorted({display_building_type(t) for t in levels.keys()}),
        }

    to_level = b.level + 1

    ok, detail = check_prereqs(building_type=b.type, to_level=to_level, levels=levels)
    if not ok:
        return {
            "allowed": False,
            "building_type": display_building_type(b.type),
            "canonical_type": b.type,
            "from_level": b.level,
            "to_level": to_level,
            "detail": detail,
        }

    cost = upgrade_cost(b.type, to_level)
    seconds = upgrade_time_seconds(b.type, to_level)

    # Resource sufficiency breakdown
    insufficient = {}
    if city.food < cost["food"]:
        insufficient["food"] = {"need": cost["food"], "have": city.food}
    if city.wood < cost["wood"]:
        insufficient["wood"] = {"need": cost["wood"], "have": city.wood}
    if city.stone < cost["stone"]:
        insufficient["stone"] = {"need": cost["stone"], "have": city.stone}
    if city.iron < cost["iron"]:
        insufficient["iron"] = {"need": cost["iron"], "have": city.iron}

    return {
        "allowed": len(insufficient) == 0,
        "building_type": display_building_type(b.type),
        "canonical_type": b.type,
        "from_level": b.level,
        "to_level": to_level,
        "cost": cost,
        "duration_seconds": seconds,
        "have_resources": len(insufficient) == 0,
        "insufficient": insufficient,
    }

@router.get("/{city_id}/upgrade/recommendations")
def upgrade_recommendations(
    city_id: int,
    limit: int = 5,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    existing = db.query(Upgrade).filter(Upgrade.city_id == city_id).first()
    if existing:
        return {
            "city_id": city_id,
            "blocked": True,
            "reason": "Upgrade already in progress",
            "active": {
                "building_type": display_building_type(existing.building_type),
                "canonical_type": existing.building_type,
                "from_level": existing.from_level,
                "to_level": existing.to_level,
                "completes_at": existing.completes_at.isoformat(),
            },
            "recommended_now": [],
            "blocked_next": [],
        }

    city_buildings = db.query(Building).filter(Building.city_id == city_id).all()
    levels = {cb.type: cb.level for cb in city_buildings}

    recommended_now = []
    blocked_next = []

    # Track keep-unlock signal
    keep_unlocks = 0

    # Evaluate all candidate upgrades
    for b in city_buildings:
        to_level = b.level + 1

        ok, detail = check_prereqs(building_type=b.type, to_level=to_level, levels=levels)
        cost = upgrade_cost(b.type, to_level)
        seconds = upgrade_time_seconds(b.type, to_level)

        affordable = not (
            city.food < cost["food"]
            or city.wood < cost["wood"]
            or city.stone < cost["stone"]
            or city.iron < cost["iron"]
        )

        item = {
            "building_type": display_building_type(b.type),
            "canonical_type": b.type,
            "from_level": b.level,
            "to_level": to_level,
            "cost": cost,
            "duration_seconds": seconds,
        }

        if ok and affordable:
            # Sort helpers
            total_cost = cost["food"] + cost["wood"] + cost["stone"] + cost["iron"]
            item["_sort_total_cost"] = total_cost
            item["_sort_duration"] = seconds
            recommended_now.append(item)
        else:
            # Only surface "next blockers" that are keep-gated or prereq-related (not “can’t afford”)
            if not ok:
                item["blocked_reason"] = detail
                blocked_next.append(item)

                # If it’s blocked by keep level, upgrading keep is strategically valuable
                if isinstance(detail, dict) and detail.get("error") == "Keep level too low":
                    keep_unlocks += 1

    # Sort recommended_now: cheapest first, then fastest
    recommended_now.sort(key=lambda x: (x["_sort_total_cost"], x["_sort_duration"]))
    for x in recommended_now:
        x.pop("_sort_total_cost", None)
        x.pop("_sort_duration", None)

    # Keep priority bump: if Keep upgrade exists in recommended_now and it unlocks things, move it up
    if keep_unlocks > 0:
        for idx, item in enumerate(recommended_now):
            if item["canonical_type"] == "townhall":
                keep_item = recommended_now.pop(idx)
                # Put it near the top but not necessarily #1
                insert_at = 1 if len(recommended_now) >= 1 else 0
                recommended_now.insert(insert_at, keep_item)
                break

    # Blocked list: show the “closest” ones first (lowest required keep, then lowest to_level)
    def _blocked_sort_key(x: dict):
        d = x.get("blocked_reason") or {}
        need_keep = d.get("need_keep_level", 999999)
        return (need_keep, x.get("to_level", 999999), x.get("canonical_type", ""))

    blocked_next.sort(key=_blocked_sort_key)

    limit = max(1, min(int(limit), 20))

    return {
        "city_id": city_id,
        "blocked": False,
        "recommended_now": recommended_now[:limit],
        "blocked_next": blocked_next[:limit],
        "note": (
            "Keep is bumped up when it unlocks blocked upgrades."
            if keep_unlocks > 0
            else "Sorted by cheapest+fastest."
        ),
    }

@router.post("/{city_id}/upgrade")
def start_upgrade(
    city_id: int,
    payload: UpgradeRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict:
    city = _get_city_or_404(db, city_id, current_user, x_admin_key)

    # One builder rule: only one active upgrade at a time per city
    existing = db.query(Upgrade).filter(Upgrade.city_id == city_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Upgrade already in progress",
                "active": {
                    "building_type": display_building_type(existing.building_type),
                    "canonical_type": existing.building_type,
                    "from_level": existing.from_level,
                    "to_level": existing.to_level,
                    "completes_at": existing.completes_at.isoformat(),
                },
            },
        )

    requested = payload.building_type
    canonical = normalize_building_type(requested)

    requested = payload.building_type
    canonical = normalize_building_type(requested)

    # --- Improvement #1: reuse one buildings query for both "b" and prereq levels ---
    city_buildings = db.query(Building).filter(Building.city_id == city_id).all()
    levels = {cb.type: cb.level for cb in city_buildings}

    b = next((cb for cb in city_buildings if cb.type == canonical), None)
    if not b:
        existing_types = [display_building_type(t) for t in levels.keys()]
        raise HTTPException(
            status_code=404,
            detail={
                "error": "Building not found",
                "requested": requested,
                "canonical": canonical,
                "available_in_city": sorted(set(existing_types)),
            },
        )

    to_level = b.level + 1

    ok, detail = check_prereqs(
        building_type=b.type,
        to_level=to_level,
        levels=levels,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    cost = upgrade_cost(b.type, to_level)

    # Check resources
    if (
        city.food < cost["food"]
        or city.wood < cost["wood"]
        or city.stone < cost["stone"]
        or city.iron < cost["iron"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Insufficient resources", "cost": cost},
        )

    # Spend resources
    city.food -= cost["food"]
    city.wood -= cost["wood"]
    city.stone -= cost["stone"]
    city.iron -= cost["iron"]

    started = datetime.utcnow()
    seconds = upgrade_time_seconds(b.type, to_level)
    completes = started + timedelta(seconds=seconds)

    up = Upgrade(
        city_id=city_id,
        building_type=b.type,
        from_level=b.level,
        to_level=to_level,
        started_at=started,
        completes_at=completes,
    )

    db.add(up)

    # --- Improvement #2: guard commit with rollback ---
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "Upgrade already in progress (db constraint)"},
        )

    return {
        "status": "started",
        "building_type": display_building_type(b.type),
        "canonical_type": b.type,
        "from_level": b.level,
        "to_level": to_level,
        "cost": cost,
        "completes_at": completes.isoformat(),
        "duration_seconds": seconds,
    }
