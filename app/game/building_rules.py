# app/game/building_rules.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


# ----------------------------
# Names / normalization
# ----------------------------

ALIAS_TO_CANONICAL: dict[str, str] = {
    # Keep / Town Hall
    "keep": "townhall",
    "townhall": "townhall",
    "town_hall": "townhall",
    "town hall": "townhall",

    # Resource fields
    "farm": "farm",

    "lumbermill": "sawmill",
    "lumber_mill": "sawmill",
    "lumber mill": "sawmill",
    "sawmill": "sawmill",

    "quarry": "quarry",
    "stone_mine": "quarry",
    "stone mine": "quarry",

    "ironmine": "ironmine",
    "iron_mine": "ironmine",
    "iron mine": "ironmine",

    # City buildings
    "warehouse": "warehouse",
    "academy": "academy",
    "barracks": "barracks",
}

CANONICAL_TO_DISPLAY: dict[str, str] = {
    "townhall": "Keep",
    "farm": "Farm",
    "sawmill": "Lumber Mill",
    "quarry": "Quarry",
    "ironmine": "Iron Mine",
    "warehouse": "Warehouse",
    "academy": "Academy",
    "barracks": "Barracks",
}


def normalize_building_type(t: str) -> str:
    key = (t or "").strip().lower().replace("-", "_").replace(" ", "_")
    return ALIAS_TO_CANONICAL.get(key, key)


def display_building_type(canonical: str) -> str:
    return CANONICAL_TO_DISPLAY.get(canonical, canonical)

def raid_carry_capacity_for_levels(levels: dict[str, int]) -> int:
    barracks = levels.get("barracks", 1)
    # Age 1: small early growth, meaningful by 5+
    # L1=500, L2=700, L3=950, L4=1250, L5=1600...
    return int(500 + (barracks - 1) * 200 + max(0, barracks - 1) ** 2 * 50)

# ----------------------------
# Rules
# ----------------------------

@dataclass(frozen=True)
class BuildingRule:
    # For now: keep it simple and Evony-ish
    # prereqs: {building_type: minimum_level}
    prereqs: Dict[str, int]
    # cap_by_keep: if True => to_level cannot exceed keep level
    cap_by_keep: bool = True


RULES: dict[str, BuildingRule] = {
    "townhall": BuildingRule(prereqs={}, cap_by_keep=False),
    "farm": BuildingRule(prereqs={"townhall": 1}),
    "sawmill": BuildingRule(prereqs={"townhall": 1}),
    "quarry": BuildingRule(prereqs={"townhall": 2}),
    "ironmine": BuildingRule(prereqs={"townhall": 3}),
    "warehouse": BuildingRule(prereqs={"townhall": 2}),
    "academy": BuildingRule(prereqs={"townhall": 3}),
    "barracks": BuildingRule(prereqs={"townhall": 2}),
}


def accepted_display_types() -> list[str]:
    # What the client can request (Evony names)
    return sorted(set(CANONICAL_TO_DISPLAY.values()))


# ----------------------------
# Cost / time (Age 1 balance pass)
# ----------------------------

AGE1_MAX_LEVEL = 10  # tweak anytime (Evony Age 1 feel)

# Per-building “weighting” (how the cost is distributed across resources)
COST_WEIGHTS: dict[str, dict[str, float]] = {
    # Keep (Town Hall): wood/stone heavy, some food, some iron
    "townhall": {"food": 1.00, "wood": 1.35, "stone": 1.00, "iron": 0.55},

    # Resource fields: mostly food/wood, light stone/iron
    "farm":     {"food": 0.90, "wood": 1.10, "stone": 0.35, "iron": 0.15},
    "sawmill":  {"food": 0.75, "wood": 1.25, "stone": 0.35, "iron": 0.15},

    # Quarry / Iron Mine: more stone/iron pressure
    "quarry":   {"food": 0.95, "wood": 1.15, "stone": 0.80, "iron": 0.25},
    "ironmine": {"food": 1.00, "wood": 1.20, "stone": 0.90, "iron": 0.40},

    # City buildings
    "warehouse": {"food": 0.90, "wood": 1.10, "stone": 0.75, "iron": 0.35},
    "barracks":  {"food": 0.90, "wood": 1.20, "stone": 0.85, "iron": 0.45},
    "academy":   {"food": 1.10, "wood": 1.30, "stone": 1.00, "iron": 0.60},
}

# A “base cost scalar” per building. Combined with the curve below.
BASE_COST: dict[str, int] = {
    "townhall": 180,
    "farm": 55,
    "sawmill": 60,
    "quarry": 75,
    "ironmine": 95,
    "warehouse": 85,
    "barracks": 95,
    "academy": 120,
}

# Time balance: base seconds and curve factor per building
BASE_TIME_SECONDS: dict[str, int] = {
    "townhall": 60,
    "farm": 18,
    "sawmill": 18,
    "quarry": 20,
    "ironmine": 22,
    "warehouse": 22,
    "barracks": 24,
    "academy": 28,
}

TIME_FACTOR: dict[str, float] = {
    "townhall": 0.75,   # Keep slower overall
    "farm": 0.50,
    "sawmill": 0.50,
    "quarry": 0.55,
    "ironmine": 0.60,
    "warehouse": 0.60,
    "barracks": 0.65,
    "academy": 0.70,
}


def _clamp_age1_level(to_level: int) -> int:
    to_level = max(1, int(to_level))
    return min(to_level, AGE1_MAX_LEVEL)


def upgrade_time_seconds(building_type: str, to_level: int) -> int:
    """
    Age 1 tuning:
    - early levels are fast (seconds)
    - quadratic-ish growth so higher levels start to matter
    - Keep is meaningfully slower
    """
    lvl = _clamp_age1_level(to_level)

    base = BASE_TIME_SECONDS.get(building_type, 20)
    factor = TIME_FACTOR.get(building_type, 0.55)

    # Curve: base + (lvl^2 * factor * base)
    seconds = int(base + (lvl * lvl) * factor * base)

    # Safety floor so nothing becomes 0 or tiny
    return max(10, seconds)


def upgrade_cost(building_type: str, to_level: int) -> dict:
    """
    Age 1 tuning:
    - costs grow roughly with lvl^2 (Evony-ish ramp)
    - per-building weights control the “shape” across resources
    """
    lvl = _clamp_age1_level(to_level)

    base = BASE_COST.get(building_type, 70)
    weights = COST_WEIGHTS.get(building_type, {"food": 1.0, "wood": 1.0, "stone": 1.0, "iron": 0.5})

    # Curve: base * lvl^2 with a small linear bump to keep early levels feeling “real”
    scalar = (base * (lvl * lvl)) + (base * 2 * lvl)

    def q(x: float) -> int:
        # quantize to nicer numbers (optional but feels better in UI/tests)
        return int(round(x / 10.0) * 10)

    return {
        "food": q(scalar * weights["food"] * 0.10),
        "wood": q(scalar * weights["wood"] * 0.10),
        "stone": q(scalar * weights["stone"] * 0.10),
        "iron": q(scalar * weights["iron"] * 0.10),
    }


# ----------------------------
# Validation helpers
# ----------------------------

def check_prereqs(
    *,
    building_type: str,
    to_level: int,
    levels: Dict[str, int],
) -> Tuple[bool, dict]:
    """
    levels: mapping canonical_type -> current_level
    """
    rule = RULES.get(building_type)
    if not rule:
        return False, {"error": "Unknown building type", "building_type": building_type}

    if to_level > AGE1_MAX_LEVEL:
        return False, {"error": "Max level reached (Age 1)", "max_level": AGE1_MAX_LEVEL}

    # prereqs met?
    missing = []
    for req_type, req_lvl in rule.prereqs.items():
        have = int(levels.get(req_type, 0))
        if have < req_lvl:
            missing.append({"type": req_type, "need": req_lvl, "have": have})

    if missing:
        return False, {"error": "Prerequisites not met", "missing": missing}

    # keep cap?
    if rule.cap_by_keep:
        keep_lvl = int(levels.get("townhall", 1))
        if to_level > keep_lvl:
            return False, {
                "error": "Keep level too low",
                "need_keep_level": to_level,
                "have_keep_level": keep_lvl,
            }

    return True, {}
