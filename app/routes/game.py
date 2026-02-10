# app/routes/game.py
from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session

from app.config import ADMIN_KEY
from app.database import get_db
from app.game.tick import tick_all_cities
from app.routes.auth import get_current_user

router = APIRouter(prefix="/game", tags=["game"])

def _is_admin(x_admin_key: str | None) -> bool:
    return bool(ADMIN_KEY) and bool(x_admin_key) and secrets.compare_digest(x_admin_key, ADMIN_KEY)

@router.post("/tick")
def run_tick(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    x_admin_key: str | None = Header(default=None),
) -> dict:
    """
    Tick is an admin operation:
    - Requires a valid Bearer token (logged-in user)
    - Requires X-Admin-Key header to match ADMIN_KEY
    """
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    now = datetime.utcnow()  # naive UTC (matches our DB)
    return tick_all_cities(db, now)
