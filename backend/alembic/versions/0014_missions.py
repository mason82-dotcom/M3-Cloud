"""Add persistent mission planning core.

Revision ID: 0014_missions
Revises: 0013_projects_surveys
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0014_missions"
down_revision = "0013_projects_surveys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "survey_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("surveys.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="WAYLINE"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="M3_CLOUD"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("aircraft_sn", sa.String(length=128), nullable=True),
        sa.Column("preferred_executor", sa.String(length=32), nullable=True),
        sa.Column("external_ref", sa.String(length=255), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("survey_id", "name", name="uq_mission_survey_name"),
    )
    op.create_index("ix_missions_survey_id", "missions", ["survey_id"])
    op.create_index("ix_missions_name", "missions", ["name"])
    op.create_index("ix_missions_kind", "missions", ["kind"])
    op.create_index("ix_missions_source", "missions", ["source"])
    op.create_index("ix_missions_status", "missions", ["status"])
    op.create_index("ix_missions_aircraft_sn", "missions", ["aircraft_sn"])
    op.create_index("ix_missions_external_ref", "missions", ["external_ref"])
    op.create_index("ix_missions_plan_sha256", "missions", ["plan_sha256"])
    op.create_index("ix_missions_created_at", "missions", ["created_at"])
    op.create_index("ix_missions_updated_at", "missions", ["updated_at"])


def downgrade() -> None:
    op.drop_table("missions")
