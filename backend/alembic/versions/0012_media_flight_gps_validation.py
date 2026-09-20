"""Add GPS/time flight validation evidence to media datasets.

Revision ID: 0012_media_flight_gps_validation
Revises: 0011_media_metadata
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_media_flight_gps_validation"
down_revision = "0011_media_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "media_datasets",
        sa.Column(
            "flight_match_details",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("media_datasets", "flight_match_details")
