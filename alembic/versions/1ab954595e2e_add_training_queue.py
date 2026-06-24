"""add training_queue

Revision ID: 1ab954595e2e
Revises: 8e7b8593c0df
Create Date: 2026-02-15 18:37:42.622157

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1ab954595e2e'
down_revision: Union[str, Sequence[str], None] = '8e7b8593c0df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.create_table(
        "training_queue",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("cities.id"), nullable=False),
        sa.Column("troop_type_id", sa.Integer(), sa.ForeignKey("troop_types.id"), nullable=False),

        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="training"),

        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finishes_at", sa.DateTime(), nullable=False),

        sa.Column("cost_food", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_wood", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_stone", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_iron", sa.Integer(), nullable=False, server_default="0"),

        sa.Column("seconds_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_training_queue_city_id", "training_queue", ["city_id"])
    op.create_index("ix_training_queue_troop_type_id", "training_queue", ["troop_type_id"])
    op.create_index("ix_training_queue_status", "training_queue", ["status"])


def downgrade():
    op.drop_index("ix_training_queue_status", table_name="training_queue")
    op.drop_index("ix_training_queue_troop_type_id", table_name="training_queue")
    op.drop_index("ix_training_queue_city_id", table_name="training_queue")
    op.drop_table("training_queue")
