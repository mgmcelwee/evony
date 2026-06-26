"""add hero assignments

Revision ID: e958feaa6cd2
Revises: e90d6d66044f
Create Date: 2026-06-26 10:43:29.541528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e958feaa6cd2'
down_revision: Union[str, Sequence[str], None] = 'e90d6d66044f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hero_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("hero_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["hero_id"], ["heroes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city_id", "role", name="uq_hero_assignment_city_role"),
        sa.UniqueConstraint("hero_id", name="uq_hero_assignment_hero"),
    )
    op.create_index(op.f("ix_hero_assignments_city_id"), "hero_assignments", ["city_id"], unique=False)
    op.create_index(op.f("ix_hero_assignments_hero_id"), "hero_assignments", ["hero_id"], unique=False)
    op.create_index(op.f("ix_hero_assignments_id"), "hero_assignments", ["id"], unique=False)
    op.create_index(op.f("ix_hero_assignments_role"), "hero_assignments", ["role"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_hero_assignments_role"), table_name="hero_assignments")
    op.drop_index(op.f("ix_hero_assignments_id"), table_name="hero_assignments")
    op.drop_index(op.f("ix_hero_assignments_hero_id"), table_name="hero_assignments")
    op.drop_index(op.f("ix_hero_assignments_city_id"), table_name="hero_assignments")
    op.drop_table("hero_assignments")
    # ### end Alembic commands ###
