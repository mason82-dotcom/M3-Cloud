from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Flight(Base):
    __tablename__ = "flights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aircraft_sn: Mapped[str] = mapped_column(String(128), index=True)
    gateway_sn: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    dji_track_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    takeoff_position = mapped_column(Geometry("POINTZ", srid=4326), nullable=True)
    landing_position = mapped_column(Geometry("POINTZ", srid=4326), nullable=True)
    path = mapped_column(Geometry("LINESTRINGZ", srid=4326), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    max_relative_altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_horizontal_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rtk_converged_samples: Mapped[int] = mapped_column(Integer, default=0)
    rtk_total_samples: Mapped[int] = mapped_column(Integer, default=0)
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    flight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("flights.id", ondelete="CASCADE"),
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source_timestamp_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    position = mapped_column(Geometry("POINTZ", srid=4326), nullable=True)
    relative_altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    ellipsoid_height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizontal_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vertical_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_convergence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gps_satellites: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rtk_satellites: Mapped[int | None] = mapped_column(Integer, nullable=True)
