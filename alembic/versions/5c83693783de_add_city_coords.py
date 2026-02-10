"""add city coords

Revision ID: 5c83693783de
Revises: a5aba138d576
Create Date: 2026-01-31 23:02:17.959044

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c83693783de'
down_revision: Union[str, Sequence[str], None] = 'a5aba138d576'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cities", sa.Column("x", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("cities", sa.Column("y", sa.Integer(), nullable=False, server_default=sa.text("0")))

def downgrade() -> None:
    op.drop_column("cities", "y")
    op.drop_column("cities", "x")
