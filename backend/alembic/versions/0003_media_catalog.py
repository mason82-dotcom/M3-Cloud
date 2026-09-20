"""Create external media catalog.

Revision ID: 0003_media_catalog
Revises: 0002_telemetry_source
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_media_catalog"
down_revision = "0002_telemetry_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("relative_path", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("extension", sa.String(length=16), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mtime_ns", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("media_kind", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
        sa.Column("capture_group", sa.String(length=768), nullable=True),
        sa.Column("storage_mode", sa.String(length=32), nullable=False, server_default="EXTERNAL"),
        sa.Column("external_root", sa.String(length=128), nullable=False, server_default="media-import"),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "duplicate_of",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_media_assets_relative_path", "media_assets", ["relative_path"], unique=True)
    op.create_index("ix_media_assets_filename", "media_assets", ["filename"])
    op.create_index("ix_media_assets_extension", "media_assets", ["extension"])
    op.create_index("ix_media_assets_sha256", "media_assets", ["sha256"])
    op.create_index("ix_media_assets_platform", "media_assets", ["platform"])
    op.create_index("ix_media_assets_media_kind", "media_assets", ["media_kind"])
    op.create_index("ix_media_assets_capture_group", "media_assets", ["capture_group"])
    op.create_index("ix_media_assets_present", "media_assets", ["present"])
    op.create_index("ix_media_assets_duplicate_of", "media_assets", ["duplicate_of"])
    op.create_index("ix_media_assets_last_seen_at", "media_assets", ["last_seen_at"])


def downgrade() -> None:
    op.drop_table("media_assets")
