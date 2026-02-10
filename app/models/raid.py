# app/models/raid.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Raid(Base):
    __tablename__ = "raids"

    id: Mapped[int] = mapped_column(primary_key=True)

    attacker_city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id"), index=True, nullable=False
    )
    target_city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id"), index=True, nullable=False
    )

    carry_capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    stolen_food: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stolen_wood: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stolen_stone: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stolen_iron: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    # enroute -> returning -> resolved
    status: Mapped[str] = mapped_column(String(20), default="enroute", nullable=False)

    outbound_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    return_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    arrives_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    returns_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
