"""Catalog native DJI Pilot 2 wayline files.

Revision ID: 0019_dji_wayline_files
Revises: 0018_dji_pilot_media
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_dji_wayline_files"
down_revision = "0018_dji_pilot_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dji_wayline_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("drone_model_key", sa.String(length=64), nullable=False),
        sa.Column(
            "payload_model_keys",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "template_types",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "favorited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="DJI_PILOT2"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "object_key",
            name="uq_dji_wayline_workspace_object",
        ),
    )
    op.create_index(
        "ix_dji_wayline_files_workspace_id",
        "dji_wayline_files",
        ["workspace_id"],
    )
    op.create_index(
        "ix_dji_wayline_files_name",
        "dji_wayline_files",
        ["name"],
    )
    op.create_index(
        "ix_dji_wayline_files_favorited",
        "dji_wayline_files",
        ["favorited"],
    )
    op.create_index(
        "ix_dji_wayline_files_drone_model_key",
        "dji_wayline_files",
        ["drone_model_key"],
    )
    op.create_index(
        "ix_dji_wayline_files_sha256",
        "dji_wayline_files",
        ["sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_dji_wayline_files_sha256", table_name="dji_wayline_files")
    op.drop_index(
        "ix_dji_wayline_files_drone_model_key",
        table_name="dji_wayline_files",
    )
    op.drop_index("ix_dji_wayline_files_favorited", table_name="dji_wayline_files")
    op.drop_index("ix_dji_wayline_files_name", table_name="dji_wayline_files")
    op.drop_index("ix_dji_wayline_files_workspace_id", table_name="dji_wayline_files")
    op.drop_table("dji_wayline_files")
