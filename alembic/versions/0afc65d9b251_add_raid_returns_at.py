"""add raid returns_at

Revision ID: 0afc65d9b251
Revises: 5c83693783de
Create Date: 2026-02-01 10:42:40.569918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0afc65d9b251'
down_revision: Union[str, Sequence[str], None] = '5c83693783de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add returns_at nullable (SQLite-friendly)
    op.add_column("raids", sa.Column("returns_at", sa.DateTime(), nullable=True))

    # Backfill legacy rows so old history still looks sane:
    # - If resolved_at exists, use it
    # - Else use arrives_at
    op.execute(
        """
        UPDATE raids
        SET returns_at = COALESCE(resolved_at, arrives_at)
        WHERE returns_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("raids", "returns_at")
