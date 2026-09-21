from app.config import Settings
from app.dji.media import classify_pilot_media, platform_from_model_key
from app.dji.storage_sts import DJIPilotStorageCredentials, pilot_storage_ready
from app.api_dji_media import _object_key_allowed


def test_m3_model_keys_stay_separate_in_media_classification():
    assert platform_from_model_key("0-77-0") == "M3E"
    assert platform_from_model_key("0-77-1") == "M3T"
    assert platform_from_model_key("0-77-2") == "M3M"

    thermal = classify_pilot_media(
        name="DJI_20260921_0001_T.JPG",
        drone_model_key="0-77-1",
    )
    assert thermal.platform == "M3T"
    assert thermal.media_kind == "THERMAL"

    multispectral = classify_pilot_media(
        name="DJI_20260921_0001_MS_NIR.TIF",
        drone_model_key="0-77-2",
    )
    assert multispectral.platform == "M3M"
    assert multispectral.media_kind == "MS_NIR"


def test_pilot_storage_is_fail_closed_without_external_endpoint_and_role():
    settings = Settings(_env_file=None)
    assert pilot_storage_ready(settings) is False


def test_pilot_storage_ready_requires_explicit_external_endpoint_and_role():
    settings = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_storage_endpoint": "http://192.168.178.45:8333",
            "dji_pilot_storage_role_arn": "arn:aws:iam::000000000000:role/m3cloud-pilot2",
            "dji_pilot_storage_provider": "minio",
        }
    )
    assert pilot_storage_ready(settings) is True


def test_dji_sts_response_shape_matches_pilot_contract():
    value = DJIPilotStorageCredentials(
        bucket="m3-media",
        endpoint="http://192.168.178.45:8333",
        provider="minio",
        region="us-east-1",
        object_key_prefix="pilot2/workspace",
        access_key_id="STS.ACCESS",
        access_key_secret="secret",
        security_token="token",
        expire=3600,
    ).as_dji_response()

    assert value["bucket"] == "m3-media"
    assert value["provider"] == "minio"
    assert value["credentials"]["access_key_id"] == "STS.ACCESS"
    assert value["credentials"]["security_token"] == "token"
    assert value["credentials"]["expire"] == 3600


def test_upload_callback_object_key_must_stay_inside_workspace_prefix():
    workspace = "e3dea0f5-37f2-4d79-ae58-490af3228069"
    assert _object_key_allowed(
        workspace,
        f"pilot2/{workspace}/DJI_0001.JPG",
    )
    assert not _object_key_allowed(
        workspace,
        "pilot2/other-workspace/DJI_0001.JPG",
    )
    assert not _object_key_allowed(
        workspace,
        f"pilot2/{workspace}/../other/DJI_0001.JPG",
    )
