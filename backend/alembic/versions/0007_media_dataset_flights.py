"""Persist media datasets and flight associations.

Revision ID: 0007_media_dataset_flights
Revises: 0006_processing_result_details
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_media_dataset_flights"
down_revision = "0006_processing_result_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("prefix", sa.String(length=1024), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column(
            "flight_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flights.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "platform",
            "prefix",
            name="uq_media_dataset_platform_prefix",
        ),
    )
    op.create_index("ix_media_datasets_prefix", "media_datasets", ["prefix"])
    op.create_index("ix_media_datasets_platform", "media_datasets", ["platform"])
    op.create_index("ix_media_datasets_flight_id", "media_datasets", ["flight_id"])
    op.create_index("ix_media_datasets_present", "media_datasets", ["present"])
    op.create_index("ix_media_datasets_updated_at", "media_datasets", ["updated_at"])

    op.add_column(
        "processing_jobs",
        sa.Column("flight_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_processing_jobs_flight_id",
        "processing_jobs",
        "flights",
        ["flight_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_processing_jobs_flight_id",
        "processing_jobs",
        ["flight_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_flight_id", table_name="processing_jobs")
    op.drop_constraint(
        "fk_processing_jobs_flight_id",
        "processing_jobs",
        type_="foreignkey",
    )
    op.drop_column("processing_jobs", "flight_id")
    op.drop_table("media_datasets")
