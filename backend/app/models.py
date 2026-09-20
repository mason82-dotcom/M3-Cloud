from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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



class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    relative_path: Mapped[str] = mapped_column(String(1024), unique=True, index=True)
    filename: Mapped[str] = mapped_column(String(512), index=True)
    extension: Mapped[str] = mapped_column(String(16), index=True)

    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)

    platform: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    media_kind: Mapped[str] = mapped_column(String(32), default="UNKNOWN", index=True)
    capture_group: Mapped[str | None] = mapped_column(String(768), nullable=True, index=True)

    storage_mode: Mapped[str] = mapped_column(String(32), default="EXTERNAL")
    external_root: Mapped[str] = mapped_column(String(128), default="media-import")
    present: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)



class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255))
    input_prefix: Mapped[str] = mapped_column(String(1024), index=True)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    media_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    options: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)

    image_count: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_count: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    remote_project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remote_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_assets: Mapped[list[str]] = mapped_column(JSON, default=list)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingJobAsset(Base):
    __tablename__ = "processing_job_assets"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
