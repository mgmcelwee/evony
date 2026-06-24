# app/models/training_queue.py
from __future__ import annotations

from datetime import datetime
from sqlalchemy import Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrainingQueue(Base):
    __tablename__ = "training_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(Integer, ForeignKey("cities.id"), index=True, nullable=False)
    troop_type_id: Mapped[int] = mapped_column(Integer, ForeignKey("troop_types.id"), index=True, nullable=False)

    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="training")  # training|processing|completed|cancelled

    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    finishes_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # Store what we charged (deterministic)
    cost_food: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_wood: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_stone: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_iron: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Optional debug/tuning
    seconds_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

