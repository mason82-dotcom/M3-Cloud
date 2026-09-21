"""Track DJI Pilot media provenance.

Revision ID: 0018_dji_pilot_media
Revises: 0017_mission_upload_status
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_dji_pilot_media"
down_revision = "0017_mission_upload_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("dji_fingerprint", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "media_assets",
        sa.Column("dji_tiny_fingerprint", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "media_assets",
        sa.Column("dji_object_key", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "media_assets",
        sa.Column("dji_source_sn", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "media_assets",
        sa.Column("dji_file_group_id", sa.String(length=128), nullable=True),
    )

    op.create_index(
        "ix_media_assets_dji_fingerprint",
        "media_assets",
        ["dji_fingerprint"],
    )
    op.create_index(
        "ix_media_assets_dji_tiny_fingerprint",
        "media_assets",
        ["dji_tiny_fingerprint"],
    )
    op.create_index(
        "ix_media_assets_dji_object_key",
        "media_assets",
        ["dji_object_key"],
        unique=True,
    )
    op.create_index(
        "ix_media_assets_dji_source_sn",
        "media_assets",
        ["dji_source_sn"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_dji_source_sn", table_name="media_assets")
    op.drop_index("ix_media_assets_dji_object_key", table_name="media_assets")
    op.drop_index("ix_media_assets_dji_tiny_fingerprint", table_name="media_assets")
    op.drop_index("ix_media_assets_dji_fingerprint", table_name="media_assets")

    op.drop_column("media_assets", "dji_file_group_id")
    op.drop_column("media_assets", "dji_source_sn")
    op.drop_column("media_assets", "dji_object_key")
    op.drop_column("media_assets", "dji_tiny_fingerprint")
    op.drop_column("media_assets", "dji_fingerprint")
