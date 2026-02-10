# app/models/troop_type.py
from __future__ import annotations

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TroopType(Base):
    __tablename__ = "troop_types"

    id: Mapped[int] = mapped_column(primary_key=True)

    # stable identifier you can use in APIs, e.g. "t1_inf"
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    tier: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # basic stats (tune later)
    attack: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    defense: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hp: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # use a simple integer rating for now (bigger = faster)
    speed: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    # carry per unit
    carry: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
