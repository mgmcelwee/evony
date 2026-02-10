"""seed troop types

Revision ID: 8e7b8593c0df
Revises: 4316f3b90b79
Create Date: 2026-02-04 21:37:14.538913

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8e7b8593c0df"
down_revision: Union[str, Sequence[str], None] = "4316f3b90b79"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent seed for SQLite: if rows already exist, do nothing.
    op.execute(
        """
        INSERT OR IGNORE INTO troop_types (code, name, tier, attack, defense, hp, speed, carry)
        VALUES
          ('t1_inf',   'T1 Infantry', 1, 10, 12, 120, 100, 5),
          ('t1_rng',   'T1 Ranged',   1, 14,  8,  90, 105, 4),
          ('t1_cav',   'T1 Cavalry',  1, 16,  9, 100, 120, 6),
          ('t1_siege', 'T1 Siege',    1, 22,  6,  80,  70, 20);
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM troop_types WHERE code IN ('t1_inf','t1_rng','t1_cav','t1_siege')")
