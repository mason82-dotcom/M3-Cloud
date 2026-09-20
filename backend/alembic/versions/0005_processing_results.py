"""Persist selected WebODM results in object storage.

Revision ID: 0005_processing_results
Revises: 0004_processing_jobs
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_processing_results"
down_revision = "0004_processing_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_name", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.String(length=128), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_id",
            "asset_name",
            name="uq_processing_result_job_asset",
        ),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_processing_results_job_id", "processing_results", ["job_id"])
    op.create_index("ix_processing_results_asset_name", "processing_results", ["asset_name"])
    op.create_index("ix_processing_results_sha256", "processing_results", ["sha256"])
    op.create_index("ix_processing_results_created_at", "processing_results", ["created_at"])


def downgrade() -> None:
    op.drop_table("processing_results")
