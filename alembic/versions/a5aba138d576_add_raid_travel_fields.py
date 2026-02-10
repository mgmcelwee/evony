"""add raid travel fields

Revision ID: a5aba138d576
Revises: 6390ad624c9b
Create Date: 2026-02-01 ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a5aba138d576"
down_revision: Union[str, Sequence[str], None] = "6390ad624c9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- copy_from schema BEFORE this migration (what 6390ad624c9b created) ---
    raids_before = sa.Table(
        "raids",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("attacker_city_id", sa.Integer(), nullable=False),
        sa.Column("target_city_id", sa.Integer(), nullable=False),
        sa.Column("carry_capacity", sa.Integer(), nullable=False),
        sa.Column("stolen_food", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_wood", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_stone", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_iron", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.ForeignKeyConstraint(["attacker_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["target_city_id"], ["cities.id"]),
    )

    # 1) Add new columns (SQLite-safe via batch mode). Use copy_from so --sql works.
    with op.batch_alter_table("raids", copy_from=raids_before) as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="resolved",  # existing rows become resolved
            )
        )
        batch_op.add_column(sa.Column("arrives_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))

    # 2) Backfill existing rows
    op.execute(sa.text("UPDATE raids SET arrives_at = created_at WHERE arrives_at IS NULL"))
    op.execute(sa.text("UPDATE raids SET resolved_at = created_at WHERE resolved_at IS NULL"))

    # --- copy_from schema AFTER step (1) but BEFORE step (3) ---
    raids_after_step1 = sa.Table(
        "raids",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("attacker_city_id", sa.Integer(), nullable=False),
        sa.Column("target_city_id", sa.Integer(), nullable=False),
        sa.Column("carry_capacity", sa.Integer(), nullable=False),
        sa.Column("stolen_food", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_wood", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_stone", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_iron", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'resolved'")),
        sa.Column("arrives_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["attacker_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["target_city_id"], ["cities.id"]),
    )

    # 3) Make arrives_at NOT NULL (SQLite requires another batch recreate)
    with op.batch_alter_table("raids", copy_from=raids_after_step1) as batch_op:
        batch_op.alter_column("arrives_at", existing_type=sa.DateTime(), nullable=False)
        # Optional: remove default if desired (not necessary)
        # batch_op.alter_column("status", existing_type=sa.String(length=20), server_default=None)


def downgrade() -> None:
    # copy_from schema AS IT EXISTS AFTER upgrade() completes
    raids_after_upgrade = sa.Table(
        "raids",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("attacker_city_id", sa.Integer(), nullable=False),
        sa.Column("target_city_id", sa.Integer(), nullable=False),
        sa.Column("carry_capacity", sa.Integer(), nullable=False),
        sa.Column("stolen_food", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_wood", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_stone", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("stolen_iron", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'resolved'")),
        sa.Column("arrives_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["attacker_city_id"], ["cities.id"]),
        sa.ForeignKeyConstraint(["target_city_id"], ["cities.id"]),
    )

    with op.batch_alter_table("raids", copy_from=raids_after_upgrade) as batch_op:
        batch_op.drop_column("resolved_at")
        batch_op.drop_column("arrives_at")
        batch_op.drop_column("status")
