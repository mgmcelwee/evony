from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDef:
    key: str
    display_name: str
    base_food: int
    base_wood: int
    base_stone: int
    base_iron: int
    base_time_s: int

RESEARCH = {
    "agriculture": ResearchDef(
        "agriculture",
        "Agriculture",
        100,
        100,
        0,
        0,
        60,
    ),
    "lumbering": ResearchDef(
        "lumbering",
        "Lumbering",
        100,
        100,
        0,
        0,
        60,
    ),
    "masonry": ResearchDef(
        "masonry",
        "Masonry",
        100,
        100,
        100,
        0,
        60,
    ),
    "iron_working": ResearchDef(
        "iron_working",
        "Iron Working",
        100,
        100,
        100,
        100,
        60,
    ),
    "construction": ResearchDef(
        "construction",
        "Construction",
        200,
        200,
        100,
        50,
        120,
    ),
    "military_tradition": ResearchDef(
        "military_tradition",
        "Military Tradition",
        200,
        200,
        200,
        100,
        120,
    ),
}

def _default_prereqs() -> dict[int, dict[str, int]]:
    return {
        level: {"academy": level}
        for level in range(1, 11)
    }


RESEARCH_PREREQS = {
    key: _default_prereqs()
    for key in RESEARCH.keys()
}

# Custom research prerequisites
# These are layered on top of the default Academy-level requirement.

# Construction 2-10 requires Masonry 1-9
for level in range(2, 11):
    RESEARCH_PREREQS["construction"][level]["masonry"] = level - 1

# Military Tradition 2-10 requires Construction 1-9
for level in range(2, 11):
    RESEARCH_PREREQS["military_tradition"][level]["construction"] = level - 1

# Iron Working 3-10 requires Masonry 1-8
for level in range(3, 11):
    RESEARCH_PREREQS["iron_working"][level]["masonry"] = level - 2

# Masonry 3-10 requires Lumbering 1-8
for level in range(3, 11):
    RESEARCH_PREREQS["masonry"][level]["lumbering"] = level - 2

# Lumbering 3-10 requires Agriculture 1-8
for level in range(3, 11):
    RESEARCH_PREREQS["lumbering"][level]["agriculture"] = level - 2

def get_research_prereqs(key: str, level: int) -> dict[str, int]:
    return RESEARCH_PREREQS.get(key, {}).get(level, {})


def research_cost(key: str, level: int) -> dict:
    r = RESEARCH[key]

    mult = 1.0 + (level - 1) * 0.5

    return {
        "food": int(r.base_food * mult),
        "wood": int(r.base_wood * mult),
        "stone": int(r.base_stone * mult),
        "iron": int(r.base_iron * mult),
    }


def research_time_seconds(key: str, level: int) -> int:
    r = RESEARCH[key]

    mult = 1.0 + (level - 1) * 0.5

    return int(r.base_time_s * mult)
