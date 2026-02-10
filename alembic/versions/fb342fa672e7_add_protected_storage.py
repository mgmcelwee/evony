"""add protected storage

Revision ID: fb342fa672e7
Revises: 36f592bd5a70
Create Date: 2026-01-31 21:43:17.994227

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fb342fa672e7'
down_revision: Union[str, Sequence[str], None] = '36f592bd5a70'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cities", sa.Column("protected_food", sa.Integer(), nullable=False, server_default=sa.text("1000")))
    op.add_column("cities", sa.Column("protected_wood", sa.Integer(), nullable=False, server_default=sa.text("1000")))
    op.add_column("cities", sa.Column("protected_stone", sa.Integer(), nullable=False, server_default=sa.text("600")))
    op.add_column("cities", sa.Column("protected_iron", sa.Integer(), nullable=False, server_default=sa.text("400")))

def downgrade() -> None:
    op.drop_column("cities", "protected_iron")
    op.drop_column("cities", "protected_stone")
    op.drop_column("cities", "protected_wood")
    op.drop_column("cities", "protected_food")

