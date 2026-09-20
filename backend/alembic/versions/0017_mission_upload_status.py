"""Track mission upload attempts without enabling execution.

Revision ID: 0017_mission_upload_status
Revises: 0016_mission_deployments
"""

from alembic import op
import sqlalchemy as sa


revision = "0017_mission_upload_status"
down_revision = "0016_mission_deployments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_deployments",
        sa.Column("upload_status", sa.String(length=32), nullable=False, server_default="SEALED"),
    )
    op.add_column(
        "mission_deployments",
        sa.Column("upload_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "mission_deployments",
        sa.Column("last_upload_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mission_deployments",
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mission_deployments",
        sa.Column("upload_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "mission_deployments",
        sa.Column("upload_details", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_mission_deployments_upload_status",
        "mission_deployments",
        ["upload_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mission_deployments_upload_status", table_name="mission_deployments")
    op.drop_column("mission_deployments", "upload_details")
    op.drop_column("mission_deployments", "upload_error")
    op.drop_column("mission_deployments", "uploaded_at")
    op.drop_column("mission_deployments", "last_upload_at")
    op.drop_column("mission_deployments", "upload_attempts")
    op.drop_column("mission_deployments", "upload_status")
