# app/models/raid_defender_troop.py
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

class RaidDefenderTroop(Base):
    __tablename__ = "raid_defender_troops"
    __table_args__ = (
        UniqueConstraint("raid_id", "troop_type_id", name="uq_raid_defender_troop_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    raid_id: Mapped[int] = mapped_column(ForeignKey("raids.id"), index=True, nullable=False)
    troop_type_id: Mapped[int] = mapped_column(ForeignKey("troop_types.id"), index=True, nullable=False)

    count_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    count_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
