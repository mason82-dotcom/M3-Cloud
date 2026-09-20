"""Add media capture time and conservative flight matching metadata.

Revision ID: 0009_media_flight_match
Revises: 0008_job_asset_snapshot
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_media_flight_match"
down_revision = "0008_job_asset_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_assets",
        sa.Column("capture_time_utc", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_media_assets_capture_time_utc",
        "media_assets",
        ["capture_time_utc"],
    )

    op.add_column(
        "media_datasets",
        sa.Column("capture_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_datasets",
        sa.Column("capture_ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_datasets",
        sa.Column(
            "flight_assignment_source",
            sa.String(length=32),
            nullable=False,
            server_default="AUTO",
        ),
    )
    op.add_column(
        "media_datasets",
        sa.Column(
            "flight_match_status",
            sa.String(length=32),
            nullable=False,
            server_default="NO_CAPTURE_TIME",
        ),
    )
    op.add_column(
        "media_datasets",
        sa.Column(
            "flight_match_candidates",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("media_datasets", "flight_match_candidates")
    op.drop_column("media_datasets", "flight_match_status")
    op.drop_column("media_datasets", "flight_assignment_source")
    op.drop_column("media_datasets", "capture_ended_at")
    op.drop_column("media_datasets", "capture_started_at")
    op.drop_index("ix_media_assets_capture_time_utc", table_name="media_assets")
    op.drop_column("media_assets", "capture_time_utc")
