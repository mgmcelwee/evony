"""drop legacy governor bonus columns

Revision ID: 7288b571b81e
Revises: 7d8cce9efa09
Create Date: 2026-06-24 14:23:31.447549

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7288b571b81e'
down_revision: Union[str, Sequence[str], None] = '7d8cce9efa09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("heroes", "governor_research_speed_bonus")
    op.drop_column("heroes", "governor_training_speed_bonus")
    op.drop_column("heroes", "governor_production_bonus")
    op.drop_column("heroes", "governor_building_speed_bonus")

def downgrade() -> None:
    op.add_column("heroes", sa.Column("governor_research_speed_bonus", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("heroes", sa.Column("governor_training_speed_bonus", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("heroes", sa.Column("governor_production_bonus", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("heroes", sa.Column("governor_building_speed_bonus", sa.Integer(), nullable=False, server_default="0"))
