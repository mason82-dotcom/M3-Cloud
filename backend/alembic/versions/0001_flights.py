"""Create persistent flight sessions and telemetry samples."""

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_flights"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "flights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aircraft_sn", sa.String(length=128), nullable=False),
        sa.Column("gateway_sn", sa.String(length=128), nullable=True),
        sa.Column("dji_track_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("takeoff_position", geoalchemy2.Geometry("POINTZ", srid=4326), nullable=True),
        sa.Column("landing_position", geoalchemy2.Geometry("POINTZ", srid=4326), nullable=True),
        sa.Column("path", geoalchemy2.Geometry("LINESTRINGZ", srid=4326), nullable=True),
        sa.Column("duration_s", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=False, server_default="0"),
        sa.Column("max_relative_altitude_m", sa.Float(), nullable=True),
        sa.Column("max_horizontal_speed_mps", sa.Float(), nullable=True),
        sa.Column("min_battery_percent", sa.Integer(), nullable=True),
        sa.Column("rtk_converged_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rtk_total_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_flights_aircraft_sn", "flights", ["aircraft_sn"])
    op.create_index("ix_flights_gateway_sn", "flights", ["gateway_sn"])
    op.create_index("ix_flights_dji_track_id", "flights", ["dji_track_id"])
    op.create_index("ix_flights_status", "flights", ["status"])
    op.create_index("ix_flights_started_at", "flights", ["started_at"])
    op.create_index("ix_flights_takeoff_position_gist", "flights", ["takeoff_position"], postgresql_using="gist")
    op.create_index("ix_flights_landing_position_gist", "flights", ["landing_position"], postgresql_using="gist")
    op.create_index("ix_flights_path_gist", "flights", ["path"], postgresql_using="gist")

    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column(
            "flight_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("flights.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_timestamp_ms", sa.BigInteger(), nullable=False),
        sa.Column("position", geoalchemy2.Geometry("POINTZ", srid=4326), nullable=True),
        sa.Column("relative_altitude_m", sa.Float(), nullable=True),
        sa.Column("ellipsoid_height_m", sa.Float(), nullable=True),
        sa.Column("horizontal_speed_mps", sa.Float(), nullable=True),
        sa.Column("vertical_speed_mps", sa.Float(), nullable=True),
        sa.Column("heading_deg", sa.Float(), nullable=True),
        sa.Column("mode_code", sa.Integer(), nullable=True),
        sa.Column("battery_percent", sa.Integer(), nullable=True),
        sa.Column("position_convergence", sa.String(length=32), nullable=True),
        sa.Column("gps_satellites", sa.Integer(), nullable=True),
        sa.Column("rtk_satellites", sa.Integer(), nullable=True),
    )
    op.create_index("ix_telemetry_samples_flight_id", "telemetry_samples", ["flight_id"])
    op.create_index("ix_telemetry_samples_recorded_at", "telemetry_samples", ["recorded_at"])
    op.create_index("ix_telemetry_samples_source_timestamp_ms", "telemetry_samples", ["source_timestamp_ms"])
    op.create_index(
        "ix_telemetry_samples_position_gist",
        "telemetry_samples",
        ["position"],
        postgresql_using="gist",
    )


def downgrade() -> None:
    op.drop_table("telemetry_samples")
    op.drop_table("flights")
