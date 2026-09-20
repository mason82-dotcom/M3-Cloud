"""Freeze media capture time on processing job assets.

Revision ID: 0010_proc_asset_capture
Revises: 0009_media_flight_match
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_proc_asset_capture"
down_revision = "0009_media_flight_match"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_job_assets",
        sa.Column("capture_time_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE processing_job_assets AS pja
        SET capture_time_utc = ma.capture_time_utc
        FROM media_assets AS ma
        WHERE ma.id = pja.media_asset_id
        """
    )


def downgrade() -> None:
    op.drop_column("processing_job_assets", "capture_time_utc")
