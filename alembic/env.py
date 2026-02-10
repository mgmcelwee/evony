from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
from app.models.session import SessionToken  # noqa: F401, E402
from app.models.building import Building  # noqa: F401, E402
from app.models.upgrade import Upgrade  # noqa: F401, E402
from app.models.raid import Raid
from app.models.troop_type import TroopType  # noqa: F401, E402
from app.models.city_troop import CityTroop  # noqa: F401, E402
from app.models.raid_troop import RaidTroop  # noqa: F401, E402

# --- Make sure project root is on sys.path so "import app..." works ---
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Alembic Config object (reads alembic.ini for logging, etc.)
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Import your app DB settings + models ---
from app.config import DATABASE_URL  # noqa: E402
from app.database import Base  # noqa: E402
from app.models.user import User  # noqa: F401, E402
from app.models.city import City  # noqa: F401, E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Override whatever is in alembic.ini and force our app DATABASE_URL.
    ini_section = config.get_section(config.config_ini_section) or {}
    ini_section["sqlalchemy.url"] = DATABASE_URL

    connectable = engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
