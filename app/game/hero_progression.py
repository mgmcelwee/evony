def xp_required_for_level(level: int) -> int:
    level = max(1, int(level or 1))
    return 100 + ((level - 1) * 50)


def add_hero_xp(hero, amount: int) -> dict:
    amount = max(0, int(amount or 0))

    level_before = int(hero.level or 1)
    xp_before = int(hero.xp or 0)

    hero.level = level_before
    hero.xp = xp_before + amount

    leveled_up = 0

    while hero.xp >= xp_required_for_level(hero.level):
        hero.xp -= xp_required_for_level(hero.level)
        hero.level += 1
        leveled_up += 1

    current_level_xp = int(hero.xp or 0)
    required = xp_required_for_level(hero.level)

    result = {
        "hero_id": int(hero.id),
        "name": hero.name,
        "specialty": hero.specialty,
        "level": level_before,
        "xp_before": xp_before,
        "xp_awarded": amount,
        "current_level_xp_after": current_level_xp,
        "xp_to_next_level": max(0, required - current_level_xp),
        "leveled_up": leveled_up > 0,
    }

    if leveled_up:
        result["new_level"] = int(hero.level)

    return result


def level_progress(hero) -> dict:
    level = int(getattr(hero, "level", 1) or 1)
    current_xp = int(getattr(hero, "xp", 0) or 0)
    required = xp_required_for_level(level)

    xp_to_next = max(0, required - current_xp)
    xp_percent = 0.0 if required <= 0 else round((current_xp / required) * 100, 2)

    return {
        "xp_to_next_level": xp_to_next,
        "xp_required_for_level": required,
        "xp_percent": xp_percent,
    }
