"""add hero progress to raids

Revision ID: e90d6d66044f
Revises: 7288b571b81e
Create Date: 2026-06-25 22:14:17.563445

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e90d6d66044f'
down_revision: Union[str, Sequence[str], None] = '7288b571b81e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raids",
        sa.Column("hero_progress_json", sa.Text(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("raids", "hero_progress_json")
