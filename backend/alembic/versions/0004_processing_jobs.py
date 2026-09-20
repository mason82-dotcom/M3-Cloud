"""Create processing jobs and frozen media selections.

Revision ID: 0004_processing_jobs
Revises: 0003_media_catalog
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_processing_jobs"
down_revision = "0003_media_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("input_prefix", sa.String(length=1024), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("media_kinds", sa.JSON(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("uploaded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remote_project_id", sa.Integer(), nullable=True),
        sa.Column("remote_task_id", sa.Integer(), nullable=True),
        sa.Column("remote_status", sa.Integer(), nullable=True),
        sa.Column("available_assets", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_processing_jobs_kind", "processing_jobs", ["kind"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index("ix_processing_jobs_input_prefix", "processing_jobs", ["input_prefix"])
    op.create_index("ix_processing_jobs_platform", "processing_jobs", ["platform"])
    op.create_index("ix_processing_jobs_created_at", "processing_jobs", ["created_at"])
    op.create_index("ix_processing_jobs_updated_at", "processing_jobs", ["updated_at"])

    op.create_table(
        "processing_job_assets",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "media_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_processing_job_assets_ordinal",
        "processing_job_assets",
        ["job_id", "ordinal"],
    )


def downgrade() -> None:
    op.drop_table("processing_job_assets")
    op.drop_table("processing_jobs")
