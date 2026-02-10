# app/models/building.py
from __future__ import annotations

from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Building(Base):
    __tablename__ = "buildings"
    __table_args__ = (
        UniqueConstraint("city_id", "type", name="uq_buildings_city_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    city: Mapped["City"] = relationship()

    # Examples: "townhall", "farm", "sawmill", "quarry", "ironmine", "warehouse", "academy", "barracks"
    type: Mapped[str] = mapped_column(String(32), nullable=False)

    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
