from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from app.media.metadata import METADATA_VERSION, extract_media_metadata


def test_extracts_basic_exif_and_prefers_exif_capture_time(tmp_path: Path) -> None:
    path = tmp_path / "M3E" / "DJI_20260920123456_0001_W.JPG"
    path.parent.mkdir(parents=True)

    image = Image.new("RGB", (16, 12), color="white")
    exif = Image.Exif()
    exif[271] = "DJI"
    exif[272] = "Mavic 3 Enterprise"
    exif[36867] = "2026:09:20 14:34:56"
    exif[36881] = "+02:00"
    exif[42036] = "24mm"
    exif[34855] = 100
    image.save(path, exif=exif)

    result = extract_media_metadata(
        path,
        default_timezone="Europe/Berlin",
        fallback_capture_time_utc=datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc),
    )

    assert result.capture_time_utc == datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc)
    assert result.capture_time_source == "EXIF_DATETIME_ORIGINAL_OFFSET"
    assert result.camera_make == "DJI"
    assert result.camera_model == "Mavic 3 Enterprise"
    assert result.image_width == 16
    assert result.image_height == 12
    assert result.iso == 100
    assert result.metadata_json["version"] == METADATA_VERSION


def test_extracts_dji_xmp_gps_altitude_and_attitude_without_rewriting_file(tmp_path: Path) -> None:
    path = tmp_path / "M3T" / "DJI_20260920123456_0001_T.JPG"
    path.parent.mkdir(parents=True)
    payload = b"""<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:Description
 xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"
 drone-dji:GpsLatitude="49.123456"
 drone-dji:GpsLongitude="8.654321"
 drone-dji:AbsoluteAltitude="+156.75"
 drone-dji:RelativeAltitude="+42.25"
 drone-dji:FlightYawDegree="+91.5"
 drone-dji:GimbalPitchDegree="-89.9"
 drone-dji:CreateDate="2026-09-20T14:34:56+02:00"/>
</x:xmpmeta>"""
    path.write_bytes(payload)
    before = path.read_bytes()

    result = extract_media_metadata(
        path,
        default_timezone="Europe/Berlin",
    )

    assert path.read_bytes() == before
    assert result.gps_latitude == 49.123456
    assert result.gps_longitude == 8.654321
    assert result.dji_absolute_altitude_m == 156.75
    assert result.dji_relative_altitude_m == 42.25
    assert result.flight_yaw_deg == 91.5
    assert result.gimbal_pitch_deg == -89.9
    assert result.capture_time_utc == datetime(2026, 9, 20, 12, 34, 56, tzinfo=timezone.utc)
    assert result.capture_time_source == "XMP_CREATE_DATE_OFFSET"
    assert "drone-dji" in result.metadata_json["xmp"]

def test_prefers_dji_utc_at_exposure_over_local_exif_or_create_date(tmp_path: Path) -> None:
    path = tmp_path / "M3T" / "DJI_0001_T.JPG"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        b'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:Description
 xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/"
 drone-dji:UTCAtExposure="2022-07-23T07:12:22.872778"
 drone-dji:CreateDate="2022-07-23T15:12:19+08:00"
 drone-dji:GpsLatitude="22.6939917"
 drone-dji:GpsLongitude="114.9658667"/>
</x:xmpmeta>'''
    )

    result = extract_media_metadata(
        path,
        default_timezone="Europe/Berlin",
        fallback_capture_time_utc=datetime(
            2022,
            7,
            23,
            13,
            12,
            19,
            tzinfo=timezone.utc,
        ),
    )

    assert result.capture_time_utc == datetime(
        2022,
        7,
        23,
        7,
        12,
        22,
        872778,
        tzinfo=timezone.utc,
    )
    assert result.capture_time_source == "XMP_DJI_UTC_AT_EXPOSURE"


def test_parses_exiftool_style_dji_utc_at_exposure() -> None:
    from app.media.metadata import _parse_dji_utc_at_exposure

    parsed, source = _parse_dji_utc_at_exposure(
        "2022:07:23 07:12:22.872778"
    )

    assert parsed == datetime(
        2022,
        7,
        23,
        7,
        12,
        22,
        872778,
        tzinfo=timezone.utc,
    )
    assert source == "XMP_DJI_UTC_AT_EXPOSURE"

