



def xp_required_for_level(level: int) -> int:
    return 100 + ((level - 1) * 50)


def add_hero_xp(hero, amount: int) -> dict:
    hero.xp = int(hero.xp or 0) + int(amount)

    leveled_up = 0

    while hero.xp >= xp_required_for_level(hero.level):
        hero.xp -= xp_required_for_level(hero.level)
        hero.level += 1
        leveled_up += 1

    return {
        "hero_id": hero.id,
        "xp_added": amount,
        "new_level": hero.level,
        "remaining_xp": hero.xp,
        "leveled_up": leveled_up,
        "next_level_xp": xp_required_for_level(hero.level),
    }
