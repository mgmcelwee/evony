# app/routes/tick_util.py
from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from app.config import TICK_ON_READ, TICK_THROTTLE_SECONDS
from app.game.tick import tick_all_cities

_LAST_GLOBAL_TICK_AT: Optional[datetime] = None

def tick_world_now(db: Session) -> datetime:
    """
    Tick-on-read with global throttle.
    Returns 'now' used for the tick (helpful for time_remaining_seconds).
    """
    global _LAST_GLOBAL_TICK_AT

    now = datetime.utcnow()

    if not TICK_ON_READ:
        return now

    if _LAST_GLOBAL_TICK_AT is not None:
        elapsed = (now - _LAST_GLOBAL_TICK_AT).total_seconds()
        if elapsed < TICK_THROTTLE_SECONDS:
            return now  # throttle hit → skip tick

    tick_all_cities(db, now)
    _LAST_GLOBAL_TICK_AT = now
    return now
