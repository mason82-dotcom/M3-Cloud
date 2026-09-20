"""Add processing result metadata/details.

Revision ID: 0006_processing_result_details
Revises: 0005_processing_results
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_processing_result_details"
down_revision = "0005_processing_results"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "processing_results",
        sa.Column(
            "details",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("processing_results", "details")
