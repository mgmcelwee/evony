# app/game/governor.py

from app.models.hero import Hero
from app.game.hero_specialties import calculate_hero_bonuses

def get_city_governor_bonus(db, city_id):
    governor = (
        db.query(Hero)
        .filter(
            Hero.city_id == city_id,
            Hero.status == "governor"
        )
        .first()
    )

    if not governor:
        return None, {}

    return governor, calculate_hero_bonuses(governor)
