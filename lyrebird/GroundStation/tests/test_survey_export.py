import csv
import json
from pathlib import Path

from lyrebird_groundstation.survey_export import (
    SurveyPackage,
    SurveyPackageBuilder,
    SurveyQuality,
    WebODMClient,
    _quality_from_rows,
    _wanted_images,
    annotate_manifest_for_webodm,
    survey_quality_warnings,
)

CSV_FIELDS = [
    "timestamp_epoch_ms",
    "image_id",
    "latitude",
    "longitude",
    "altitude_m",
    "rtk_latitude",
    "rtk_longitude",
    "rtk_altitude_m",
    "rtk_solution",
    "rtk_real3d_latitude",
    "rtk_real3d_longitude",
    "rtk_real3d_altitude_m",
    "aircraft_roll_deg",
    "aircraft_pitch_deg",
    "aircraft_yaw_deg",
    "heading_deg",
    "gimbal_roll_deg",
    "gimbal_pitch_deg",
    "gimbal_yaw_deg",
    "zoom_focal_length_mm",
    "optical_focal_length_mm",
    "hybrid_focal_length_mm",
]


def _row(image_id, rtk_solution="FIXED_POINT"):
    return {field: "" for field in CSV_FIELDS} | {"image_id": image_id, "rtk_solution": rtk_solution}


def test_wanted_images_deduplicates_preserving_order():
    rows = [
        _row("DJI_0001.JPG"),
        _row(""),
        _row("DJI_0001.JPG"),
        _row("DJI_0002.JPG"),
    ]
    assert _wanted_images(rows) == ["DJI_0001.JPG", "DJI_0002.JPG"]


def test_quality_counts_fixed_float_and_other():
    rows = [
        _row("a", "FIXED_POINT"),
        _row("b", "FLOAT"),
        _row("c", "SINGLE_POINT"),
        _row("d", "FIXED_POINT"),
    ]
    quality = _quality_from_rows(rows)
    assert quality == SurveyQuality(total_rows=4, fixed=2, float_count=1, other=1)
    assert quality.fixed_ratio == 0.5
    assert quality.usable_ratio == 0.75


def test_quality_warning_flags_low_fixed_ratio_and_failed_downloads():
    quality = SurveyQuality(total_rows=100, fixed=90, float_count=7, other=3)
    warnings = survey_quality_warnings(quality, ("DJI_0099.JPG",))
    assert any("90.0%" in warning for warning in warnings)
    assert any("failed to download" in warning for warning in warnings)


def test_quality_warning_silent_when_all_fixed():
    quality = SurveyQuality(total_rows=10, fixed=10, float_count=0, other=0)
    assert survey_quality_warnings(quality, ()) == []


class FakeDrone:
    IP_RC = "192.168.1.42"
    drone_name = "m3e"

    def __init__(self, reports: dict[str, Path]):
        self.reports = reports
        self.downloaded: list[str] = []

    def downloadTodaySurveyReports(self, out_dir="."):
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        result = {}
        for key, source in self.reports.items():
            dest = target / source.name
            dest.write_bytes(source.read_bytes())
            result[key] = str(dest)
        return result

    def downloadByName(self, file_name, save_path=None, out_dir="."):
        self.downloaded.append(file_name)
        Path(save_path).write_bytes(b"x" * 10)
        return save_path


def _write_captures_csv(path: Path, rows: list[dict[str, str]]):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_builder_downloads_every_logged_image_and_writes_manifest(tmp_path):
    captures = tmp_path / "mapping_2026-09-18.csv"
    _write_captures_csv(
        captures,
        [_row("DJI_0001.JPG", "FIXED_POINT"), _row("DJI_0002.JPG", "FLOAT")],
    )
    geo = tmp_path / "geo.txt"
    geo.write_text("EPSG:4326\nDJI_0001.JPG 8.6 49.1 143.0\n", encoding="utf-8")

    drone = FakeDrone({"captures": captures, "geo": geo})
    package = SurveyPackageBuilder(drone).build(tmp_path / "out")

    assert drone.downloaded == ["DJI_0001.JPG", "DJI_0002.JPG"]
    assert [path.name for path in package.images] == ["DJI_0001.JPG", "DJI_0002.JPG"]
    assert (package.images_dir / "geo.txt").is_file()
    assert package.manifest_json.is_file()
    manifest = json.loads(package.manifest_json.read_text(encoding="utf-8"))
    assert manifest["quality"]["rtkFixed"] == 1
    assert manifest["quality"]["rtkFloat"] == 1


def test_builder_raises_when_fewer_than_two_images(tmp_path):
    captures = tmp_path / "mapping_2026-09-18.csv"
    _write_captures_csv(captures, [_row("DJI_0001.JPG")])
    geo = tmp_path / "geo.txt"
    geo.write_text("EPSG:4326\n", encoding="utf-8")

    drone = FakeDrone({"captures": captures, "geo": geo})
    try:
        SurveyPackageBuilder(drone).build(tmp_path / "out")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "at least 2" in str(exc)


def test_manifest_records_selected_webodm_recipe(tmp_path):
    manifest = tmp_path / "survey.json"
    manifest.write_text('{"schemaVersion":1}', encoding="utf-8")
    package = SurveyPackage(
        root=tmp_path,
        images_dir=tmp_path / "images",
        captures_csv=tmp_path / "captures.csv",
        geo_txt=tmp_path / "geo.txt",
        manifest_json=manifest,
        images=(),
        failed_images=(),
        quality=SurveyQuality(0, 0, 0, 0),
    )

    annotate_manifest_for_webodm(
        package,
        profile_name="m3e-3d-building",
        options=[{"name": "mesh-size", "value": 600000}],
    )

    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["webodm"]["profile"] == "m3e-3d-building"
    assert data["webodm"]["options"] == [{"name": "mesh-size", "value": 600000}]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def post(self, url, data=None, files=None, timeout=None):
        self.calls.append((url, data, files is not None, timeout))
        if url.endswith("/api/projects/"):
            return FakeResponse({"id": 7})
        if url.endswith("/api/projects/7/tasks/"):
            return FakeResponse({"id": 11})
        if url.endswith("/commit/"):
            return FakeResponse({"id": 11, "status": 10})
        return FakeResponse({"uploaded": True})


def test_webodm_uses_partial_upload_then_commit_including_geo_txt(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image1 = images_dir / "DJI_1.JPG"
    image2 = images_dir / "DJI_2.JPG"
    geo = images_dir / "geo.txt"
    image1.write_bytes(b"1")
    image2.write_bytes(b"2")
    geo.write_text("EPSG:4326\n", encoding="utf-8")

    package = SurveyPackage(
        root=tmp_path,
        images_dir=images_dir,
        captures_csv=tmp_path / "captures.csv",
        geo_txt=tmp_path / "geo.txt",
        manifest_json=tmp_path / "survey.json",
        images=(image1, image2, geo),
        failed_images=(),
        quality=SurveyQuality(2, 2, 0, 0),
    )
    session = FakeSession()
    client = WebODMClient("http://webodm.local", token="abc", session=session)

    project_id, task_id, _task = client.upload_package(package, project_name="M3E")

    assert (project_id, task_id) == (7, 11)
    urls = [call[0] for call in session.calls]
    assert urls == [
        "http://webodm.local/api/projects/",
        "http://webodm.local/api/projects/7/tasks/",
        "http://webodm.local/api/projects/7/tasks/11/upload/",
        "http://webodm.local/api/projects/7/tasks/11/upload/",
        "http://webodm.local/api/projects/7/tasks/11/upload/",
        "http://webodm.local/api/projects/7/tasks/11/commit/",
    ]
    partial_task_data = session.calls[1][1]
    assert partial_task_data["partial"] == "true"
    assert session.headers["Authorization"] == "JWT abc"
