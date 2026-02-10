# app/models/city_troop.py
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CityTroop(Base):
    __tablename__ = "city_troops"
    __table_args__ = (
        UniqueConstraint("city_id", "troop_type_id", name="uq_city_troop_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    troop_type_id: Mapped[int] = mapped_column(ForeignKey("troop_types.id"), index=True, nullable=False)

    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
