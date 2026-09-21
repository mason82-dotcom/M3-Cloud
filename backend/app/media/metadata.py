from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image


METADATA_VERSION = 1
_XMP_SCAN_BYTES = 8 * 1024 * 1024
_XMP_ATTRIBUTE = re.compile(
    rb'(?P<prefix>[A-Za-z][A-Za-z0-9_.-]*):(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*["\'](?P<value>[^"\']*)["\']'
)
_XMP_ELEMENT = re.compile(
    rb'<(?P<prefix>[A-Za-z][A-Za-z0-9_.-]*):(?P<name>[A-Za-z_][A-Za-z0-9_.-]*)[^>]*>(?P<value>[^<]*)</(?P=prefix):(?P=name)>'
)


@dataclass(frozen=True)
class ExtractedMetadata:
    capture_time_utc: datetime | None
    capture_time_source: str
    metadata_status: str
    metadata_error: str | None
    camera_make: str | None
    camera_model: str | None
    camera_serial: str | None
    lens_model: str | None
    image_width: int | None
    image_height: int | None
    orientation: int | None
    exposure_time_s: float | None
    f_number: float | None
    iso: int | None
    focal_length_mm: float | None
    focal_length_35mm: float | None
    gps_latitude: float | None
    gps_longitude: float | None
    gps_altitude_m: float | None
    gps_altitude_ref: str | None
    dji_absolute_altitude_m: float | None
    dji_relative_altitude_m: float | None
    flight_yaw_deg: float | None
    flight_pitch_deg: float | None
    flight_roll_deg: float | None
    gimbal_yaw_deg: float | None
    gimbal_pitch_deg: float | None
    gimbal_roll_deg: float | None
    metadata_json: dict[str, Any]


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    result = str(value).strip().strip("\x00")
    return result or None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")[:32768]
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    number = _number(value)
    if number is not None:
        return number
    return str(value)[:32768]


def _parse_offset(value: str | None) -> timezone | None:
    if not value:
        return None
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value.strip())
    if not match:
        return None
    minutes = int(match.group(2)) * 60 + int(match.group(3))
    if match.group(1) == "-":
        minutes = -minutes
    return timezone(timedelta(minutes=minutes))


def _parse_exif_datetime(
    value: Any,
    offset: Any,
    subsecond: Any,
    *,
    default_timezone: str,
) -> tuple[datetime | None, str | None]:
    text = _text(value)
    if not text:
        return None, None
    try:
        parsed = datetime.strptime(text[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None

    sub = _text(subsecond)
    if sub and sub.isdigit():
        parsed = parsed.replace(microsecond=int((sub + "000000")[:6]))

    explicit = _parse_offset(_text(offset))
    if explicit is not None:
        return parsed.replace(tzinfo=explicit).astimezone(timezone.utc), "EXIF_DATETIME_ORIGINAL_OFFSET"

    try:
        zone = ZoneInfo(default_timezone)
    except Exception:
        zone = timezone.utc
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc), "EXIF_DATETIME_ORIGINAL_LOCAL"


def _parse_dji_utc_at_exposure(
    value: str | None,
) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    text = value.strip()
    if re.match(r"^\d{4}:\d{2}:\d{2}[ T]", text):
        text = (
            f"{text[:4]}-{text[5:7]}-{text[8:10]}"
            f"T{text[11:]}"
        )
    elif " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed, "XMP_DJI_UTC_AT_EXPOSURE"


def _parse_xmp_datetime(
    value: str | None,
    *,
    default_timezone: str,
) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None:
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(default_timezone))
        except Exception:
            parsed = parsed.replace(tzinfo=timezone.utc)
        source = "XMP_CREATE_DATE_LOCAL"
    else:
        source = "XMP_CREATE_DATE_OFFSET"
    return parsed.astimezone(timezone.utc), source


def _gps_coordinate(value: Any, ref: Any) -> float | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    degrees = _number(value[0])
    minutes = _number(value[1])
    seconds = _number(value[2])
    if degrees is None or minutes is None or seconds is None:
        return None
    result = degrees + minutes / 60.0 + seconds / 3600.0
    reference = (_text(ref) or "").upper()
    if reference in {"S", "W"}:
        result = -result
    return result


def _extract_exif(image: Image.Image) -> tuple[dict[int, Any], dict[Any, Any]]:
    exif: dict[int, Any] = {}
    gps: dict[Any, Any] = {}
    try:
        source = image.getexif()
        exif = {int(key): value for key, value in source.items()}
        try:
            gps = dict(source.get_ifd(34853))
        except Exception:
            raw = source.get(34853)
            if isinstance(raw, dict):
                gps = raw
    except Exception:
        pass
    return exif, gps


def _read_xmp_bytes(path: Path, image: Image.Image | None) -> bytes:
    candidates: list[bytes] = []
    if image is not None:
        for key in ("xmp", "XML:com.adobe.xmp"):
            value = image.info.get(key)
            if isinstance(value, bytes):
                candidates.append(value)
            elif isinstance(value, str):
                candidates.append(value.encode("utf-8", errors="replace"))
        tags = getattr(image, "tag_v2", None)
        if tags is not None:
            try:
                value = tags.get(700)
                if isinstance(value, bytes):
                    candidates.append(value)
                elif isinstance(value, str):
                    candidates.append(value.encode("utf-8", errors="replace"))
            except Exception:
                pass

    if candidates:
        return b"\n".join(candidates)

    with path.open("rb") as handle:
        return handle.read(_XMP_SCAN_BYTES)


def _extract_xmp(path: Path, image: Image.Image | None) -> dict[str, dict[str, str]]:
    payload = _read_xmp_bytes(path, image)
    result: dict[str, dict[str, str]] = {}

    for pattern in (_XMP_ATTRIBUTE, _XMP_ELEMENT):
        for match in pattern.finditer(payload):
            prefix = match.group("prefix").decode("ascii", errors="ignore")
            if prefix.lower() == "xmlns":
                continue
            name = match.group("name").decode("ascii", errors="ignore")
            value = match.group("value").decode("utf-8", errors="replace").strip()
            if len(value) > 32768:
                value = value[:32768]
            result.setdefault(prefix, {}).setdefault(name, value)

    return result


def _xmp_value(xmp: dict[str, dict[str, str]], name: str) -> str | None:
    wanted = name.casefold()
    for values in xmp.values():
        for key, value in values.items():
            if key.casefold() == wanted:
                return value
    return None


def _xmp_number(xmp: dict[str, dict[str, str]], name: str) -> float | None:
    value = _xmp_value(xmp, name)
    if value is None:
        return None
    return _number(value.strip().lstrip("+"))


def extract_media_metadata(
    path: Path,
    *,
    default_timezone: str,
    fallback_capture_time_utc: datetime | None = None,
) -> ExtractedMetadata:
    warnings: list[str] = []
    image: Image.Image | None = None
    exif: dict[int, Any] = {}
    gps: dict[Any, Any] = {}
    width: int | None = None
    height: int | None = None

    try:
        image = Image.open(path)
        width, height = image.size
        exif, gps = _extract_exif(image)
    except Exception as exc:
        warnings.append(f"image:{type(exc).__name__}")

    try:
        xmp = _extract_xmp(path, image)
    except Exception as exc:
        xmp = {}
        warnings.append(f"xmp:{type(exc).__name__}")
    finally:
        if image is not None:
            try:
                image.close()
            except Exception:
                pass

    exif_time, exif_source = _parse_exif_datetime(
        exif.get(36867) or exif.get(306),
        exif.get(36881) or exif.get(36880),
        exif.get(37521) or exif.get(37520),
        default_timezone=default_timezone,
    )
    dji_utc_time, dji_utc_source = _parse_dji_utc_at_exposure(
        _xmp_value(xmp, "UTCAtExposure"),
    )
    xmp_time, xmp_source = _parse_xmp_datetime(
        _xmp_value(xmp, "CreateDate"),
        default_timezone=default_timezone,
    )
    capture_time = (
        dji_utc_time
        or exif_time
        or xmp_time
        or fallback_capture_time_utc
    )
    capture_source = (
        dji_utc_source
        or exif_source
        or xmp_source
        or ("FILENAME" if fallback_capture_time_utc is not None else "NONE")
    )

    gps_latitude = _gps_coordinate(gps.get(2), gps.get(1))
    gps_longitude = _gps_coordinate(gps.get(4), gps.get(3))
    if gps_latitude is None:
        gps_latitude = _xmp_number(xmp, "GpsLatitude")
    if gps_longitude is None:
        gps_longitude = _xmp_number(xmp, "GpsLongitude")

    gps_altitude = _number(gps.get(6))
    gps_altitude_ref = None
    if gps_altitude is not None:
        raw_ref = gps.get(5, 0)
        ref_value = _integer(raw_ref[0] if isinstance(raw_ref, bytes) and raw_ref else raw_ref)
        if ref_value == 1:
            gps_altitude = -abs(gps_altitude)
            gps_altitude_ref = "BELOW_SEA_LEVEL"
        else:
            gps_altitude = abs(gps_altitude)
            gps_altitude_ref = "ABOVE_SEA_LEVEL"

    exif_summary = {
        "Make": _text(exif.get(271)),
        "Model": _text(exif.get(272)),
        "Orientation": _integer(exif.get(274)),
        "DateTimeOriginal": _text(exif.get(36867)),
        "OffsetTimeOriginal": _text(exif.get(36881)),
        "BodySerialNumber": _text(exif.get(42033)),
        "LensModel": _text(exif.get(42036)),
        "ExposureTime": _json_value(exif.get(33434)),
        "FNumber": _json_value(exif.get(33437)),
        "ISO": _integer(exif.get(34855)),
        "FocalLength": _json_value(exif.get(37386)),
        "FocalLengthIn35mmFilm": _json_value(exif.get(41989)),
    }
    exif_summary = {key: value for key, value in exif_summary.items() if value is not None}

    has_metadata = bool(exif_summary or gps or xmp)
    if has_metadata and warnings:
        status = "PARTIAL"
    elif has_metadata:
        status = "READY"
    elif warnings:
        status = "NO_METADATA"
    else:
        status = "NO_METADATA"

    metadata_json: dict[str, Any] = {
        "version": METADATA_VERSION,
        "exif": exif_summary,
        "xmp": xmp,
    }
    if gps:
        metadata_json["exif_gps"] = {str(key): _json_value(value) for key, value in gps.items()}
    if warnings:
        metadata_json["warnings"] = warnings

    return ExtractedMetadata(
        capture_time_utc=capture_time,
        capture_time_source=capture_source,
        metadata_status=status,
        metadata_error="; ".join(warnings) if warnings else None,
        camera_make=_text(exif.get(271)) or _xmp_value(xmp, "Make"),
        camera_model=_text(exif.get(272)) or _xmp_value(xmp, "Model"),
        camera_serial=_text(exif.get(42033)) or _xmp_value(xmp, "SerialNumber"),
        lens_model=_text(exif.get(42036)),
        image_width=width,
        image_height=height,
        orientation=_integer(exif.get(274)),
        exposure_time_s=_number(exif.get(33434)),
        f_number=_number(exif.get(33437)),
        iso=_integer(exif.get(34855)),
        focal_length_mm=_number(exif.get(37386)),
        focal_length_35mm=_number(exif.get(41989)),
        gps_latitude=gps_latitude,
        gps_longitude=gps_longitude,
        gps_altitude_m=gps_altitude,
        gps_altitude_ref=gps_altitude_ref,
        dji_absolute_altitude_m=_xmp_number(xmp, "AbsoluteAltitude"),
        dji_relative_altitude_m=_xmp_number(xmp, "RelativeAltitude"),
        flight_yaw_deg=_xmp_number(xmp, "FlightYawDegree"),
        flight_pitch_deg=_xmp_number(xmp, "FlightPitchDegree"),
        flight_roll_deg=_xmp_number(xmp, "FlightRollDegree"),
        gimbal_yaw_deg=_xmp_number(xmp, "GimbalYawDegree"),
        gimbal_pitch_deg=_xmp_number(xmp, "GimbalPitchDegree"),
        gimbal_roll_deg=_xmp_number(xmp, "GimbalRollDegree"),
        metadata_json=metadata_json,
    )


def asset_metadata_payload(asset: Any) -> dict[str, Any]:
    capture_time = getattr(asset, "capture_time_utc", None)
    return {
        "metadata_version": getattr(asset, "metadata_version", 0),
        "status": getattr(asset, "metadata_status", "PENDING"),
        "error": getattr(asset, "metadata_error", None),
        "capture_time_utc": capture_time.isoformat() if capture_time else None,
        "capture_time_source": getattr(asset, "capture_time_source", None),
        "camera": {
            "make": getattr(asset, "camera_make", None),
            "model": getattr(asset, "camera_model", None),
            "serial": getattr(asset, "camera_serial", None),
            "lens_model": getattr(asset, "lens_model", None),
        },
        "image": {
            "width": getattr(asset, "image_width", None),
            "height": getattr(asset, "image_height", None),
            "orientation": getattr(asset, "orientation", None),
            "exposure_time_s": getattr(asset, "exposure_time_s", None),
            "f_number": getattr(asset, "f_number", None),
            "iso": getattr(asset, "iso", None),
            "focal_length_mm": getattr(asset, "focal_length_mm", None),
            "focal_length_35mm": getattr(asset, "focal_length_35mm", None),
        },
        "gps": {
            "latitude": getattr(asset, "gps_latitude", None),
            "longitude": getattr(asset, "gps_longitude", None),
            "altitude_m": getattr(asset, "gps_altitude_m", None),
            "altitude_ref": getattr(asset, "gps_altitude_ref", None),
        },
        "dji_altitude": {
            "absolute_ellipsoid_m": getattr(asset, "dji_absolute_altitude_m", None),
            "relative_takeoff_m": getattr(asset, "dji_relative_altitude_m", None),
        },
        "flight_attitude": {
            "yaw_deg": getattr(asset, "flight_yaw_deg", None),
            "pitch_deg": getattr(asset, "flight_pitch_deg", None),
            "roll_deg": getattr(asset, "flight_roll_deg", None),
        },
        "gimbal_attitude": {
            "yaw_deg": getattr(asset, "gimbal_yaw_deg", None),
            "pitch_deg": getattr(asset, "gimbal_pitch_deg", None),
            "roll_deg": getattr(asset, "gimbal_roll_deg", None),
        },
        "raw": getattr(asset, "metadata_json", None) or {},
    }
