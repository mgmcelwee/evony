# app/models/building_upgrade.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BuildingUpgrade(Base):
    __tablename__ = "building_upgrades"
    __table_args__ = (
        # For now: only one active building upgrade per city
        UniqueConstraint("city_id", "status", name="uq_building_upgrades_city_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)

    # status is kept generic so later you can also store "research", "troop_train", etc.
    status: Mapped[str] = mapped_column(String(24), default="building", index=True, nullable=False)

    building_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    from_level: Mapped[int] = mapped_column(Integer, nullable=False)
    to_level: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completes_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)

    # Snapshot cost (helps debugging + deterministic tests)
    cost_food: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_wood: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_stone: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_iron: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
