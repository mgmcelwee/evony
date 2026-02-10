# app/game/raid_mail.py
from __future__ import annotations

import json
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.raid import Raid
from app.models.city import City
from app.models.raid_troop import RaidTroop
from app.models.raid_defender_troop import RaidDefenderTroop
from app.models.troop_type import TroopType
from app.game.mailbox import send_mail


def _round2(x: float) -> float:
    return round(float(x), 2)


def _atk_unit_power(tt: TroopType) -> float:
    # match your tick.py weights
    return float(getattr(tt, "attack", 0) or 0) + 0.10 * float(getattr(tt, "hp", 0) or 0)


def _def_unit_power(tt: TroopType) -> float:
    return float(getattr(tt, "defense", 0) or 0) + 0.10 * float(getattr(tt, "hp", 0) or 0)


def send_raid_result_mail(db: Session, *, raid_id: int, now: datetime) -> None:
    """
    Safe to call from tick.py.
    - Does NOT call tick_all_cities or _build_combat_report
    - Does NOT commit; caller's transaction handles that
    """
    raid = db.query(Raid).filter(Raid.id == raid_id).first()
    if not raid:
        return

    attacker_city = db.query(City).filter(City.id == raid.attacker_city_id).first()
    defender_city = db.query(City).filter(City.id == raid.target_city_id).first()
    if not attacker_city or not defender_city:
        return

    # --- Attacker totals (sent/lost) + reconstructed power ---
    atk_lines = (
        db.query(RaidTroop, TroopType)
        .join(TroopType, TroopType.id == RaidTroop.troop_type_id)
        .filter(RaidTroop.raid_id == raid.id)
        .all()
    )

    atk_sent = 0
    atk_lost = 0
    atk_power_start = 0.0
    atk_power_lost = 0.0

    for rt, tt in atk_lines:
        sent = int(getattr(rt, "count_sent", 0) or 0)
        lost = int(getattr(rt, "count_lost", 0) or 0)
        unit = _atk_unit_power(tt)
        atk_sent += sent
        atk_lost += lost
        atk_power_start += sent * unit
        atk_power_lost += lost * unit

    # --- Defender snapshot totals (start/lost) + reconstructed power ---
    def_lines = (
        db.query(RaidDefenderTroop, TroopType)
        .join(TroopType, TroopType.id == RaidDefenderTroop.troop_type_id)
        .filter(RaidDefenderTroop.raid_id == raid.id)
        .all()
    )

    def_start = 0
    def_lost = 0
    def_power_start = 0.0
    def_power_lost = 0.0

    for rdt, tt in def_lines:
        start = int(getattr(rdt, "count_start", 0) or 0)
        lost = int(getattr(rdt, "count_lost", 0) or 0)
        unit = _def_unit_power(tt)
        def_start += start
        def_lost += lost
        def_power_start += start * unit
        def_power_lost += lost * unit

    # Outcome hint (same simple logic you used in report)
    outcome_hint = None
    if atk_power_start > 0 and def_power_start > 0:
        ratio = def_power_start / (atk_power_start + def_power_start)
        outcome_hint = "attacker_advantage" if ratio < 0.5 else "defender_advantage"

    subject = f"Raid #{raid.id} resolved — {outcome_hint or 'combat_report'}"

    loot = {
        "food": int(getattr(raid, "stolen_food", 0) or 0),
        "wood": int(getattr(raid, "stolen_wood", 0) or 0),
        "stone": int(getattr(raid, "stolen_stone", 0) or 0),
        "iron": int(getattr(raid, "stolen_iron", 0) or 0),
    }

    body = (
        f"Raid #{raid.id} resolved.\n"
        f"Attacker: {attacker_city.name} (City {attacker_city.id})\n"
        f"Defender: {defender_city.name} (City {defender_city.id})\n"
        f"\n"
        f"Attacker troops: sent={atk_sent}, lost={atk_lost}, returning={max(0, atk_sent - atk_lost)}\n"
        f"Defender troops: start={def_start}, lost={def_lost}, remaining={max(0, def_start - def_lost)}\n"
        f"\n"
        f"Power (reconstructed): atk_start={_round2(atk_power_start)} atk_lost={_round2(atk_power_lost)}\n"
        f"                     def_start={_round2(def_power_start)} def_lost={_round2(def_power_lost)}\n"
        f"\n"
        f"Loot: food={loot['food']} wood={loot['wood']} stone={loot['stone']} iron={loot['iron']}\n"
        f"\n"
        f"Full report: /raids/{raid.id}/report.html\n"
    )

    payload = {
        "raid_id": raid.id,
        "status": raid.status,
        "resolved_at": raid.resolved_at.isoformat() if raid.resolved_at else None,
        "outcome_hint": outcome_hint,
        "loot": loot,
        "attacker": {
            "city_id": attacker_city.id,
            "name": attacker_city.name,
            "sent": atk_sent,
            "lost": atk_lost,
            "returning": max(0, atk_sent - atk_lost),
            "power_start": _round2(atk_power_start),
            "power_lost": _round2(atk_power_lost),
        },
        "defender": {
            "city_id": defender_city.id,
            "name": defender_city.name,
            "start": def_start,
            "lost": def_lost,
            "remaining": max(0, def_start - def_lost),
            "power_start": _round2(def_power_start),
            "power_lost": _round2(def_power_lost),
        },
    }

    # send to both owners
    send_mail(
        db,
        user_id=int(attacker_city.owner_id),
        kind="raid_report",
        subject=subject,
        body=body,
        payload=payload,
    )
    send_mail(
        db,
        user_id=int(defender_city.owner_id),
        kind="raid_report",
        subject=subject,
        body=body,
        payload=payload,
    )
