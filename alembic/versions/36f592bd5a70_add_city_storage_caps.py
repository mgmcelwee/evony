"""add city storage caps

Revision ID: 36f592bd5a70
Revises: 36667c20c59b
Create Date: 2026-01-31 21:27:46.433307

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36f592bd5a70'
down_revision: Union[str, Sequence[str], None] = '36667c20c59b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires DEFAULT values when adding NOT NULL columns
    op.add_column(
        "cities",
        sa.Column("max_food", sa.Integer(), nullable=False, server_default=sa.text("5000")),
    )
    op.add_column(
        "cities",
        sa.Column("max_wood", sa.Integer(), nullable=False, server_default=sa.text("5000")),
    )
    op.add_column(
        "cities",
        sa.Column("max_stone", sa.Integer(), nullable=False, server_default=sa.text("3000")),
    )
    op.add_column(
        "cities",
        sa.Column("max_iron", sa.Integer(), nullable=False, server_default=sa.text("2000")),
    )


def downgrade() -> None:
    op.drop_column("cities", "max_iron")
    op.drop_column("cities", "max_stone")
    op.drop_column("cities", "max_wood")
    op.drop_column("cities", "max_food")
