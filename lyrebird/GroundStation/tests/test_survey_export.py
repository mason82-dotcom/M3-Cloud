import csv
import json
from pathlib import Path

from lyrebird_groundstation.survey_export import (
    SurveyPackage,
    SurveyPackageBuilder,
    SurveyQuality,
    WebODMClient,
    _quality_from_summary,
    _wanted_images,
    annotate_manifest_for_webodm,
    survey_quality_warnings,
)

CSV_FIELDS = [
    "seq",
    "event_time_ms",
    "media_index",
    "file_name",
    "file_size_bytes",
    "file_type",
    "media_resolved",
    "lens",
    "rtk_quality",
    "rtk_fix",
    "rtk_healthy",
    "rtk_age_ms",
]


def _row(name, *, size=10, resolved=True, quality="FIXED"):
    return {field: "" for field in CSV_FIELDS} | {
        "file_name": name,
        "file_size_bytes": str(size),
        "file_type": "JPEG",
        "media_resolved": "true" if resolved else "false",
        "rtk_quality": quality,
        "rtk_fix": quality,
    }


def _summary(total=2, fixed=2, floating=0, stale=0, missing=0):
    return {
        "schemaVersion": 1,
        "totalCaptures": total,
        "resolvedFiles": total,
        "unresolvedFiles": 0,
        "rtkFixed": fixed,
        "rtkFloat": floating,
        "rtkStale": stale,
        "rtkMissing": missing,
    }


def test_wanted_images_uses_actual_reconciled_schema():
    rows = [
        _row("DJI_0001.JPG"),
        _row("DJI_0001.JPG"),
        _row("DJI_0002.JPG", resolved=False),
        _row("DJI_0003.JPG"),
    ]
    assert _wanted_images(rows) == ["DJI_0001.JPG", "DJI_0003.JPG"]


def test_quality_comes_from_summary_json():
    quality = _quality_from_summary(_summary(total=4, fixed=2, floating=1, stale=1))
    assert quality == SurveyQuality(total_rows=4, fixed=2, float_count=1, stale=1, missing=0)
    assert quality.fixed_ratio == 0.5
    assert quality.usable_ratio == 0.75


def test_quality_warning_flags_low_fixed_ratio_and_failed_downloads():
    quality = SurveyQuality(total_rows=100, fixed=90, float_count=7, stale=2, missing=1)
    warnings = survey_quality_warnings(quality, ("DJI_0099.JPG",))
    assert any("90.0%" in warning for warning in warnings)
    assert any("failed validation/download" in warning for warning in warnings)


class FakeDrone:
    IP_RC = "192.168.1.42"
    drone_name = "m3e"

    def __init__(self, captures: Path, summary: Path):
        self.captures = captures
        self.summary = summary
        self.downloaded: list[str] = []

    def getLatestSurveyInfo(self):
        return {
            "available": True,
            "capturesName": self.captures.name,
            "summaryName": self.summary.name,
        }

    def downloadLatestSurveyReports(self, out_dir="."):
        target = Path(out_dir)
        target.mkdir(parents=True, exist_ok=True)
        captures = target / self.captures.name
        summary = target / self.summary.name
        captures.write_bytes(self.captures.read_bytes())
        summary.write_bytes(self.summary.read_bytes())
        return {"captures": str(captures), "summary": str(summary)}

    def downloadByName(self, file_name, save_path=None, out_dir="."):
        self.downloaded.append(file_name)
        Path(save_path).write_bytes(b"x" * 10)
        return save_path


def _write_captures_csv(path: Path, rows: list[dict[str, str]]):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_builder_downloads_only_resolved_files_and_preserves_summary(tmp_path):
    captures = tmp_path / "10-30-00_m3e_captures.csv"
    _write_captures_csv(
        captures,
        [
            _row("DJI_0001.JPG", size=10),
            _row("DJI_0002.JPG", size=10),
            _row("DJI_0003.JPG", size=10, resolved=False),
        ],
    )
    summary = tmp_path / "10-30-00_m3e_survey-summary.json"
    summary.write_text(json.dumps(_summary(total=3, fixed=2, missing=1)), encoding="utf-8")

    drone = FakeDrone(captures, summary)
    package = SurveyPackageBuilder(drone).build(tmp_path / "out")

    assert drone.downloaded == ["DJI_0001.JPG", "DJI_0002.JPG"]
    assert [path.name for path in package.images] == ["DJI_0001.JPG", "DJI_0002.JPG"]
    assert package.summary_json.name.endswith("_survey-summary.json")
    manifest = json.loads(package.manifest_json.read_text(encoding="utf-8"))
    assert manifest["quality"]["rtkFixed"] == 2
    assert manifest["reports"]["summary"] == summary.name


def test_builder_rejects_wrong_download_size(tmp_path):
    captures = tmp_path / "survey_captures.csv"
    _write_captures_csv(captures, [_row("DJI_1.JPG", size=11), _row("DJI_2.JPG", size=10)])
    summary = tmp_path / "survey_survey-summary.json"
    summary.write_text(json.dumps(_summary()), encoding="utf-8")

    package = SurveyPackageBuilder(FakeDrone(captures, summary)).build(tmp_path / "out")
    assert package.failed_images == ("DJI_1.JPG",)
    assert [path.name for path in package.images] == ["DJI_2.JPG"]


def test_manifest_records_selected_webodm_recipe(tmp_path):
    manifest = tmp_path / "survey.json"
    manifest.write_text('{"schemaVersion":1}', encoding="utf-8")
    package = SurveyPackage(
        root=tmp_path,
        images_dir=tmp_path / "images",
        captures_csv=tmp_path / "captures.csv",
        summary_json=tmp_path / "summary.json",
        manifest_json=manifest,
        images=(),
        failed_images=(),
        quality=SurveyQuality(0, 0, 0, 0, 0),
    )
    annotate_manifest_for_webodm(
        package,
        profile_name="m3e-3d-building",
        options=[{"name": "mesh-size", "value": 600000}],
    )
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["webodm"]["profile"] == "m3e-3d-building"


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


def test_webodm_uploads_only_images_then_commits(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    image1 = images_dir / "DJI_1.JPG"
    image2 = images_dir / "DJI_2.JPG"
    image1.write_bytes(b"1")
    image2.write_bytes(b"2")
    package = SurveyPackage(
        root=tmp_path,
        images_dir=images_dir,
        captures_csv=tmp_path / "captures.csv",
        summary_json=tmp_path / "summary.json",
        manifest_json=tmp_path / "survey.json",
        images=(image1, image2),
        failed_images=(),
        quality=SurveyQuality(2, 2, 0, 0, 0),
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
        "http://webodm.local/api/projects/7/tasks/11/commit/",
    ]
    assert session.headers["Authorization"] == "JWT abc"
