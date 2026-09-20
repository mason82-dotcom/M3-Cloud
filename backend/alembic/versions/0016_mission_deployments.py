"""Add immutable mission deployment handoff packages.

Revision ID: 0016_mission_deployments
Revises: 0015_mission_revisions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_mission_deployments"
down_revision = "0015_mission_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_version", sa.Integer(), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("aircraft_sn", sa.String(length=128), nullable=False),
        sa.Column("preferred_executor", sa.String(length=32), nullable=True),
        sa.Column("package_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mission_deployments_mission_id", "mission_deployments", ["mission_id"])
    op.create_index("ix_mission_deployments_revision_version", "mission_deployments", ["revision_version"])
    op.create_index("ix_mission_deployments_plan_sha256", "mission_deployments", ["plan_sha256"])
    op.create_index("ix_mission_deployments_aircraft_sn", "mission_deployments", ["aircraft_sn"])
    op.create_index(
        "ix_mission_deployments_package_sha256",
        "mission_deployments",
        ["package_sha256"],
        unique=True,
    )
    op.create_index("ix_mission_deployments_created_at", "mission_deployments", ["created_at"])


def downgrade() -> None:
    op.drop_table("mission_deployments")
