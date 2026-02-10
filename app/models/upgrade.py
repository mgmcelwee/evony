# app/models/upgrade.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Upgrade(Base):
    __tablename__ = "upgrades"
    __table_args__ = (
        # One active upgrade per city for now (Evony-like "one builder" rule)
        UniqueConstraint("city_id", name="uq_upgrades_one_per_city"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    city: Mapped["City"] = relationship()

    building_type: Mapped[str] = mapped_column(String(32), nullable=False)
    from_level: Mapped[int] = mapped_column(Integer, nullable=False)
    to_level: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completes_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
