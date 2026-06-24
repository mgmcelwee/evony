VALID_HERO_SPECIALTIES = {
    "SCHOLAR",
    "BUILDER",
    "DRILLMASTER",
    "GENERAL",
    "DEFENDER",
    "SCOUT",
}


DEFAULT_GOVERNOR_BONUSES = {
    "research_speed_bonus": 0.0,
    "training_speed_bonus": 0.0,
    "building_speed_bonus": 0.0,
    "production_bonus": 0.0,
    "march_speed_bonus": 0.0,
    "attack_bonus": 0.0,
    "defense_bonus": 0.0,
}


SPECIALTY_BONUS_PER_LEVEL = {
    "SCHOLAR": {
        "research_speed_bonus": 0.01,
        "production_bonus": 0.0025,
    },
    "BUILDER": {
        "building_speed_bonus": 0.01,
        "production_bonus": 0.0025,
    },
    "DRILLMASTER": {
        "training_speed_bonus": 0.01,
        "production_bonus": 0.0025,
    },
    "GENERAL": {
        "attack_bonus": 0.01,
        "production_bonus": 0.0025,
    },
    "DEFENDER": {
        "defense_bonus": 0.01,
        "production_bonus": 0.0025,
    },
    "SCOUT": {
        "march_speed_bonus": 0.01,
        "production_bonus": 0.0025,
    },
}


def normalize_specialty(specialty: str | None) -> str:
    if not specialty:
        return "GENERAL"

    specialty = specialty.upper().strip()

    if specialty not in VALID_HERO_SPECIALTIES:
        return "GENERAL"

    return specialty


def calculate_hero_bonuses(hero) -> dict:
    specialty = normalize_specialty(getattr(hero, "specialty", "GENERAL"))
    level = getattr(hero, "level", 1) or 1

    rules = SPECIALTY_BONUS_PER_LEVEL.get(specialty, {})

    bonuses = DEFAULT_GOVERNOR_BONUSES.copy()

    for bonus_name, rate_per_level in rules.items():
        bonuses[bonus_name] = round(rate_per_level * level, 4)

    return bonuses
