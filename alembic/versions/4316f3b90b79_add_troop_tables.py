"""add troop tables

Revision ID: 4316f3b90b79
Revises: b1269dbd630d
Create Date: 2026-02-04 20:52:16.513197
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4316f3b90b79"
down_revision: Union[str, Sequence[str], None] = "b1269dbd630d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create troop_types
    op.create_table(
        "troop_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("attack", sa.Integer(), nullable=False),
        sa.Column("defense", sa.Integer(), nullable=False),
        sa.Column("hp", sa.Integer(), nullable=False),
        sa.Column("speed", sa.Integer(), nullable=False),
        sa.Column("carry", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_troop_types_code"), "troop_types", ["code"], unique=True)

    # Create city_troops
    op.create_table(
        "city_troops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("troop_type_id", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["troop_type_id"], ["troop_types.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city_id", "troop_type_id", name="uq_city_troop_type"),
    )
    op.create_index(op.f("ix_city_troops_city_id"), "city_troops", ["city_id"], unique=False)
    op.create_index(op.f("ix_city_troops_troop_type_id"), "city_troops", ["troop_type_id"], unique=False)

    # Create raid_troops
    op.create_table(
        "raid_troops",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raid_id", sa.Integer(), nullable=False),
        sa.Column("troop_type_id", sa.Integer(), nullable=False),
        sa.Column("count_sent", sa.Integer(), nullable=False),
        sa.Column("count_lost", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["raid_id"], ["raids.id"]),
        sa.ForeignKeyConstraint(["troop_type_id"], ["troop_types.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raid_id", "troop_type_id", name="uq_raid_troop_type"),
    )
    op.create_index(op.f("ix_raid_troops_raid_id"), "raid_troops", ["raid_id"], unique=False)
    op.create_index(op.f("ix_raid_troops_troop_type_id"), "raid_troops", ["troop_type_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_raid_troops_troop_type_id"), table_name="raid_troops")
    op.drop_index(op.f("ix_raid_troops_raid_id"), table_name="raid_troops")
    op.drop_table("raid_troops")

    op.drop_index(op.f("ix_city_troops_troop_type_id"), table_name="city_troops")
    op.drop_index(op.f("ix_city_troops_city_id"), table_name="city_troops")
    op.drop_table("city_troops")

    op.drop_index(op.f("ix_troop_types_code"), table_name="troop_types")
    op.drop_table("troop_types")
