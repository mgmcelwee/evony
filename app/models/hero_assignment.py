from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class HeroAssignment(Base):
    __tablename__ = "hero_assignments"

    id = Column(Integer, primary_key=True, index=True)

    city_id = Column(Integer, ForeignKey("cities.id"), nullable=False, index=True)
    hero_id = Column(Integer, ForeignKey("heroes.id"), nullable=False, index=True)

    role = Column(String, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("city_id", "role", name="uq_hero_assignment_city_role"),
        UniqueConstraint("hero_id", name="uq_hero_assignment_hero"),
    )

    hero = relationship("Hero")
    city = relationship("City")
