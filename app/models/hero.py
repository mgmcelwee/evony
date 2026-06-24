from sqlalchemy import Column, Integer, String, ForeignKey
from app.database import Base


class Hero(Base):
    __tablename__ = "heroes"

    id = Column(Integer, primary_key=True, index=True)
    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    level = Column(Integer, nullable=False, default=1)
    xp = Column(Integer, nullable=False, default=0)

    attack_bonus = Column(Integer, nullable=False, default=0)
    defense_bonus = Column(Integer, nullable=False, default=0)
    march_speed_bonus = Column(Integer, nullable=False, default=0)
    training_speed_bonus = Column(Integer, nullable=False, default=0)
    research_speed_bonus = Column(Integer, nullable=False, default=0)
    specialty = Column(String, nullable=False, default="GENERAL")
    status = Column(String, nullable=False, default="idle")
