# app/models/research_queue.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ResearchQueue(Base):
    __tablename__ = "research_queue"
    __table_args__ = (
        UniqueConstraint("city_id", name="uq_research_queue_one_per_city"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    city: Mapped["City"] = relationship()

    research_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    from_level: Mapped[int] = mapped_column(Integer, nullable=False)
    to_level: Mapped[int] = mapped_column(Integer, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finishes_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(24), default="researching", index=True, nullable=False)

    cost_food: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_wood: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_stone: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_iron: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
