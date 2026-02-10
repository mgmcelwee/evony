# app/models/city.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Ownership
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    owner: Mapped["User"] = relationship(back_populates="cities")

    # Core identity
    name: Mapped[str] = mapped_column(String(40), nullable=False)

    # Map position (tile coords)
    # NOTE: server_default is important for SQLite migrations when adding NOT NULL columns
    x: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    y: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Basic Evony-like stats (we’ll expand later)
    townhall_level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # Resources (very simple starting model)
    food: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    wood: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    stone: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    iron: Mapped[int] = mapped_column(Integer, default=500, nullable=False)

    # Max Resources
    max_food: Mapped[int] = mapped_column(Integer, default=5000, nullable=False)
    max_wood: Mapped[int] = mapped_column(Integer, default=5000, nullable=False)
    max_stone: Mapped[int] = mapped_column(Integer, default=3000, nullable=False)
    max_iron: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)

    # March speed buffs (percent)
    march_speed_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    return_speed_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Protected Resources
    protected_food: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    protected_wood: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    protected_stone: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    protected_iron: Mapped[int] = mapped_column(Integer, default=400, nullable=False)

    # Tick system (naive UTC)
    last_tick_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)

    # Production rates (per minute). We'll tie these to buildings later.
    food_rate: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    wood_rate: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    stone_rate: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    iron_rate: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
