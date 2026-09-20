"""Extract and freeze image EXIF/GPS/DJI XMP metadata.

Revision ID: 0011_media_metadata
Revises: 0010_proc_asset_capture
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_media_metadata"
down_revision = "0010_proc_asset_capture"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("capture_time_source", sa.String(length=64), nullable=True))
    op.add_column("media_assets", sa.Column("metadata_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("media_assets", sa.Column("metadata_status", sa.String(length=32), nullable=False, server_default="PENDING"))
    op.add_column("media_assets", sa.Column("metadata_error", sa.Text(), nullable=True))

    for name, length in (
        ("camera_make", 128),
        ("camera_model", 128),
        ("camera_serial", 128),
        ("lens_model", 255),
    ):
        op.add_column("media_assets", sa.Column(name, sa.String(length=length), nullable=True))

    for name in ("image_width", "image_height", "orientation", "iso"):
        op.add_column("media_assets", sa.Column(name, sa.Integer(), nullable=True))

    for name in (
        "exposure_time_s",
        "f_number",
        "focal_length_mm",
        "focal_length_35mm",
        "gps_latitude",
        "gps_longitude",
        "gps_altitude_m",
        "dji_absolute_altitude_m",
        "dji_relative_altitude_m",
        "flight_yaw_deg",
        "flight_pitch_deg",
        "flight_roll_deg",
        "gimbal_yaw_deg",
        "gimbal_pitch_deg",
        "gimbal_roll_deg",
    ):
        op.add_column("media_assets", sa.Column(name, sa.Float(), nullable=True))

    op.add_column("media_assets", sa.Column("gps_altitude_ref", sa.String(length=32), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column(
            "metadata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )

    op.create_index("ix_media_assets_metadata_status", "media_assets", ["metadata_status"])
    op.create_index("ix_media_assets_gps_latitude", "media_assets", ["gps_latitude"])
    op.create_index("ix_media_assets_gps_longitude", "media_assets", ["gps_longitude"])

    op.add_column(
        "processing_job_assets",
        sa.Column(
            "metadata_snapshot",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.execute(
        """
        UPDATE processing_job_assets
        SET metadata_snapshot = json_build_object(
            'metadata_version', 0,
            'capture_time_utc',
            CASE
                WHEN capture_time_utc IS NULL THEN NULL
                ELSE to_char(capture_time_utc AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
            END,
            'capture_time_source', 'LEGACY'
        )
        """
    )


def downgrade() -> None:
    op.drop_column("processing_job_assets", "metadata_snapshot")

    op.drop_index("ix_media_assets_gps_longitude", table_name="media_assets")
    op.drop_index("ix_media_assets_gps_latitude", table_name="media_assets")
    op.drop_index("ix_media_assets_metadata_status", table_name="media_assets")

    for name in (
        "metadata_json",
        "gps_altitude_ref",
        "gimbal_roll_deg",
        "gimbal_pitch_deg",
        "gimbal_yaw_deg",
        "flight_roll_deg",
        "flight_pitch_deg",
        "flight_yaw_deg",
        "dji_relative_altitude_m",
        "dji_absolute_altitude_m",
        "gps_altitude_m",
        "gps_longitude",
        "gps_latitude",
        "focal_length_35mm",
        "focal_length_mm",
        "f_number",
        "exposure_time_s",
        "iso",
        "orientation",
        "image_height",
        "image_width",
        "lens_model",
        "camera_serial",
        "camera_model",
        "camera_make",
        "metadata_error",
        "metadata_status",
        "metadata_version",
        "capture_time_source",
    ):
        op.drop_column("media_assets", name)
