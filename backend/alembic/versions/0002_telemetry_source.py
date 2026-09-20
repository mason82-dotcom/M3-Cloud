"""Record telemetry source provenance.

Revision ID: 0002_telemetry_source
Revises: 0001_flights
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_telemetry_source"
down_revision = "0001_flights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Every persisted sample before source-neutral recording was introduced came
    # through the DJI Cloud OSD observer, so this backfill is deterministic.
    op.add_column(
        "telemetry_samples",
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="dji_cloud",
        ),
    )
    op.create_index(
        "ix_telemetry_samples_source",
        "telemetry_samples",
        ["source"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_samples_source", table_name="telemetry_samples")
    op.drop_column("telemetry_samples", "source")
