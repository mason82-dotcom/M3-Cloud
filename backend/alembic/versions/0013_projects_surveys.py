"""Add projects and surveys.

Revision ID: 0013_projects_surveys
Revises: 0012_media_flight_gps_validation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013_projects_surveys"
down_revision = "0012_media_flight_gps_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_name", "projects", ["name"])
    op.create_index("ix_projects_status", "projects", ["status"])
    op.create_index("ix_projects_created_at", "projects", ["created_at"])
    op.create_index("ix_projects_updated_at", "projects", ["updated_at"])

    op.create_table(
        "surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="GENERIC"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_survey_project_name"),
    )
    op.create_index("ix_surveys_project_id", "surveys", ["project_id"])
    op.create_index("ix_surveys_name", "surveys", ["name"])
    op.create_index("ix_surveys_kind", "surveys", ["kind"])
    op.create_index("ix_surveys_status", "surveys", ["status"])
    op.create_index("ix_surveys_created_at", "surveys", ["created_at"])
    op.create_index("ix_surveys_updated_at", "surveys", ["updated_at"])

    for table in ("flights", "media_datasets", "processing_jobs"):
        op.add_column(
            table,
            sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            f"fk_{table}_survey_id_surveys",
            table,
            "surveys",
            ["survey_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_survey_id", table, ["survey_id"])


def downgrade() -> None:
    for table in ("processing_jobs", "media_datasets", "flights"):
        op.drop_index(f"ix_{table}_survey_id", table_name=table)
        op.drop_constraint(
            f"fk_{table}_survey_id_surveys",
            table,
            type_="foreignkey",
        )
        op.drop_column(table, "survey_id")

    op.drop_table("surveys")
    op.drop_table("projects")
