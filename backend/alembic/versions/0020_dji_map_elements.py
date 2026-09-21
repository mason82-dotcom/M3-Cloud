"""Store DJI Pilot 2 map elements.

Revision ID: 0020_dji_map_elements
Revises: 0019_dji_wayline_files
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_dji_map_elements"
down_revision = "0019_dji_wayline_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dji_map_elements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("user_name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_dji_map_elements_workspace_id",
        "dji_map_elements",
        ["workspace_id"],
    )
    op.create_index(
        "ix_dji_map_elements_group_id",
        "dji_map_elements",
        ["group_id"],
    )
    op.create_index(
        "ix_dji_map_elements_name",
        "dji_map_elements",
        ["name"],
    )


def downgrade() -> None:
    op.drop_index("ix_dji_map_elements_name", table_name="dji_map_elements")
    op.drop_index("ix_dji_map_elements_group_id", table_name="dji_map_elements")
    op.drop_index("ix_dji_map_elements_workspace_id", table_name="dji_map_elements")
    op.drop_table("dji_map_elements")
