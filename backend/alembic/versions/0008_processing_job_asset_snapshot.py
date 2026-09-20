"""Freeze processing input metadata on each job asset.

Revision ID: 0008_job_asset_snapshot
Revises: 0007_media_dataset_flights
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_job_asset_snapshot"
down_revision = "0007_media_dataset_flights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("processing_job_assets", sa.Column("relative_path", sa.String(length=1024), nullable=True))
    op.add_column("processing_job_assets", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("processing_job_assets", sa.Column("sha256", sa.String(length=64), nullable=True))
    op.add_column("processing_job_assets", sa.Column("media_kind", sa.String(length=32), nullable=True))
    op.add_column("processing_job_assets", sa.Column("capture_group", sa.String(length=768), nullable=True))

    op.execute(
        """
        UPDATE processing_job_assets AS pja
        SET
            relative_path = ma.relative_path,
            size_bytes = ma.size_bytes,
            sha256 = ma.sha256,
            media_kind = ma.media_kind,
            capture_group = ma.capture_group
        FROM media_assets AS ma
        WHERE ma.id = pja.media_asset_id
        """
    )

    op.alter_column("processing_job_assets", "relative_path", nullable=False)
    op.alter_column("processing_job_assets", "size_bytes", nullable=False)
    op.alter_column("processing_job_assets", "sha256", nullable=False)
    op.alter_column("processing_job_assets", "media_kind", nullable=False)


def downgrade() -> None:
    op.drop_column("processing_job_assets", "capture_group")
    op.drop_column("processing_job_assets", "media_kind")
    op.drop_column("processing_job_assets", "sha256")
    op.drop_column("processing_job_assets", "size_bytes")
    op.drop_column("processing_job_assets", "relative_path")
