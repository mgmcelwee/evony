"""add city tick and rates

Revision ID: bc5ff0aac48f
Revises: 28385af59ce4
Create Date: 2026-01-31 19:48:43.542596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc5ff0aac48f'
down_revision: Union[str, Sequence[str], None] = '28385af59ce4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite can't always add a column with a non-constant default (e.g. CURRENT_TIMESTAMP)
    # during ALTER TABLE. So we:
    # 1) add last_tick_at as nullable
    # 2) backfill existing rows using CURRENT_TIMESTAMP
    # 3) add the rate columns with constant defaults (OK in SQLite)

    op.add_column(
        "cities",
        sa.Column("last_tick_at", sa.DateTime(), nullable=True),
    )

    # Backfill existing rows
    op.execute("UPDATE cities SET last_tick_at = CURRENT_TIMESTAMP WHERE last_tick_at IS NULL")

    # Production rate columns (constant defaults are OK)
    op.add_column(
        "cities",
        sa.Column("food_rate", sa.Integer(), nullable=False, server_default=sa.text("30")),
    )
    op.add_column(
        "cities",
        sa.Column("wood_rate", sa.Integer(), nullable=False, server_default=sa.text("30")),
    )
    op.add_column(
        "cities",
        sa.Column("stone_rate", sa.Integer(), nullable=False, server_default=sa.text("20")),
    )
    op.add_column(
        "cities",
        sa.Column("iron_rate", sa.Integer(), nullable=False, server_default=sa.text("10")),
    )


def downgrade() -> None:
    op.drop_column("cities", "iron_rate")
    op.drop_column("cities", "stone_rate")
    op.drop_column("cities", "wood_rate")
    op.drop_column("cities", "food_rate")
    op.drop_column("cities", "last_tick_at")

    # ### end Alembic commands ###
