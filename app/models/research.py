# app/models/research.py
from __future__ import annotations

from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Research(Base):
    __tablename__ = "research"
    __table_args__ = (
        UniqueConstraint("city_id", "research_key", name="uq_research_city_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"), index=True, nullable=False)
    city: Mapped["City"] = relationship()

    research_key: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
