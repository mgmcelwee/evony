"""add protected storage

Revision ID: 0e7216d3fb36
Revises: fb342fa672e7
Create Date: 2026-01-31 21:56:14.681693

"""
from typing import Sequence, Union

from alembic import op, context
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e7216d3fb36'
down_revision: Union[str, Sequence[str], None] = 'fb342fa672e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: `alembic upgrade --sql` runs in offline mode with a MockConnection.
    # Any PRAGMA / SELECT inspection will crash, so we skip that logic in offline mode.
    if context.is_offline_mode():
        return

    bind = op.get_bind()
    rows = bind.execute(sa.text("PRAGMA table_info(cities);")).fetchall()
    existing_cols = {r[1] for r in rows}  # r[1] is column name

    def add_col_if_missing(name: str, default_sql: str) -> None:
        if name in existing_cols:
            return
        op.add_column(
            "cities",
            sa.Column(name, sa.Integer(), nullable=False, server_default=sa.text(default_sql)),
        )

    # SQLite-safe constant defaults
    add_col_if_missing("protected_food", "1000")
    add_col_if_missing("protected_wood", "1000")
    add_col_if_missing("protected_stone", "600")
    add_col_if_missing("protected_iron", "400")


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("PRAGMA table_info(cities);")).fetchall()
    existing_cols = {r[1] for r in rows}

    # SQLite "DROP COLUMN" support depends on version; batch_alter_table is safest.
    with op.batch_alter_table("cities") as batch_op:
        if "protected_iron" in existing_cols:
            batch_op.drop_column("protected_iron")
        if "protected_stone" in existing_cols:
            batch_op.drop_column("protected_stone")
        if "protected_wood" in existing_cols:
            batch_op.drop_column("protected_wood")
        if "protected_food" in existing_cols:
            batch_op.drop_column("protected_food")
