# app/game/buildings.py
from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class BuildingDef:
    key: str
    name: str
    max_level: int
    base_time_s: int
    # base costs (level 1), scaled up by curve
    base_food: int
    base_wood: int
    base_stone: int
    base_iron: int


BUILDINGS: dict[str, BuildingDef] = {
    # Core
    "keep":        BuildingDef("keep",        "Keep",        35,  20,  200, 200, 100,  50),
    "wall":        BuildingDef("wall",        "Wall",        35,  15,  150, 250, 150,  50),
    "academy":     BuildingDef("academy",     "Academy",     35,  25,  250, 250, 200,  75),
    "barracks":    BuildingDef("barracks",    "Barracks",    35,  20,  200, 250, 150,  75),
    "stable":      BuildingDef("stable",      "Stable",      35,  20,  250, 200, 150,  75),
    "archer_camp": BuildingDef("archer_camp", "Archer Camp", 35,  20,  200, 250, 150,  75),
    "workshop":    BuildingDef("workshop",    "Workshop",    35,  25,  200, 200, 250, 100),
    "market":      BuildingDef("market",      "Market",      35,  20,  150, 300, 150,  75),
    "embassy":     BuildingDef("embassy",     "Embassy",     35,  15,  150, 150, 150,  50),
    "tavern":      BuildingDef("tavern",      "Tavern",      35,  20,  200, 200, 150,  75),

    # Resource spots
    "farm":        BuildingDef("farm",        "Farm",        35,  10,  120,  80,  40,  20),
    "sawmill":     BuildingDef("sawmill",     "Sawmill",     35,  10,   80, 120,  40,  20),
    "quarry":      BuildingDef("quarry",      "Quarry",      35,  10,   80,  80, 120,  20),
    "mine":        BuildingDef("mine",        "Mine",        35,  10,   60,  60,  60,  60),
}


def upgrade_cost(defn: BuildingDef, to_level: int) -> dict[str, int]:
    # Simple exponential-ish curve (tunable)
    # L1 ~ base, L10 ~ ~6x, L20 ~ ~15x, etc.
    mult = 1.0 + (to_level ** 1.35) / 6.0
    return {
        "food":  int(defn.base_food * mult),
        "wood":  int(defn.base_wood * mult),
        "stone": int(defn.base_stone * mult),
        "iron":  int(defn.base_iron * mult),
    }


def upgrade_time_seconds(defn: BuildingDef, to_level: int) -> int:
    # Curve: scales with level, still fast early game
    # L1: base_time_s, L10: ~ 5-7x, L20: ~ 15x
    mult = 1.0 + (to_level ** 1.25) / 4.0
    return max(1, int(defn.base_time_s * mult))
