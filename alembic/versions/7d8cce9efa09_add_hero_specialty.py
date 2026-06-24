"""add hero specialty

Revision ID: 7d8cce9efa09
Revises: d9a19f7e555c
Create Date: 2026-06-24 10:27:45.708060

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d8cce9efa09'
down_revision: Union[str, Sequence[str], None] = 'd9a19f7e555c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "heroes",
        sa.Column(
            "specialty",
            sa.String(),
            nullable=False,
            server_default="GENERAL",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("heroes", "specialty")
