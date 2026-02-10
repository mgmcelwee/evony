# app/config.py
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "game.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"

# Admin override key (single source of truth)
ADMIN_KEY: str = os.getenv("ADMIN_KEY", "")

# Optional: centralize these too (recommended since you already use them in cities.py)
TICK_ON_READ: bool = os.getenv("TICK_ON_READ", "1") == "1"
TICK_THROTTLE_SECONDS: int = int(os.getenv("TICK_THROTTLE_SECONDS", "1"))
