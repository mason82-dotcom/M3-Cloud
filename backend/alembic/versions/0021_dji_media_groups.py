"""Track DJI Pilot media upload groups.

Revision ID: 0021_dji_media_groups
Revises: 0020_dji_map_elements
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_dji_media_groups"
down_revision = "0020_dji_map_elements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dji_media_groups",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("file_group_id", sa.String(length=128), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("file_uploaded_count", sa.Integer(), nullable=False),
        sa.Column("catalogued_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "file_group_id",
            name="uq_dji_media_group_workspace_file_group",
        ),
    )
    op.create_index(
        "ix_dji_media_groups_workspace_id",
        "dji_media_groups",
        ["workspace_id"],
    )
    op.create_index(
        "ix_dji_media_groups_file_group_id",
        "dji_media_groups",
        ["file_group_id"],
    )
    op.create_index(
        "ix_dji_media_groups_status",
        "dji_media_groups",
        ["status"],
    )
    op.create_index(
        "ix_dji_media_groups_platform",
        "dji_media_groups",
        ["platform"],
    )


def downgrade() -> None:
    op.drop_index("ix_dji_media_groups_platform", table_name="dji_media_groups")
    op.drop_index("ix_dji_media_groups_status", table_name="dji_media_groups")
    op.drop_index("ix_dji_media_groups_file_group_id", table_name="dji_media_groups")
    op.drop_index("ix_dji_media_groups_workspace_id", table_name="dji_media_groups")
    op.drop_table("dji_media_groups")
