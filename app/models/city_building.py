# app/models/city_building.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CityBuilding(Base):
    __tablename__ = "city_buildings"
    __table_args__ = (
        UniqueConstraint("city_id", "key", name="uq_city_buildings_city_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)  # e.g. "keep", "farm"
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)    # 0 = not built yet

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
