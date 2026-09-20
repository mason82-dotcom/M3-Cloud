"""Add immutable mission revisions.

Revision ID: 0015_mission_revisions
Revises: 0014_missions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_mission_revisions"
down_revision = "0014_missions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_revisions",
        sa.Column(
            "mission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_mission_revisions_plan_sha256",
        "mission_revisions",
        ["plan_sha256"],
    )
    op.create_index(
        "ix_mission_revisions_created_at",
        "mission_revisions",
        ["created_at"],
    )

    op.execute(
        """
        INSERT INTO mission_revisions (
            mission_id,
            version,
            plan_sha256,
            item_count,
            plan_json,
            created_at
        )
        SELECT
            id,
            plan_version,
            plan_sha256,
            item_count,
            plan_json,
            updated_at
        FROM missions
        """
    )


def downgrade() -> None:
    op.drop_table("mission_revisions")
