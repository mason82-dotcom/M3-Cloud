import pytest

from app.dji.models.m3 import (
    M3ThingModelValidationError,
    is_m3_identity,
    m3_model_name,
    validate_m3_property_patch,
)
from app.dji.models.rc_pro import is_rc_pro_enterprise_identity


def test_m3_model_identity_keeps_variants_separate():
    assert is_m3_identity(77, 0)
    assert is_m3_identity(77, 1)
    assert is_m3_identity(77, 2)
    assert not is_m3_identity(77, 3)
    assert not is_m3_identity(True, 1)

    assert m3_model_name(0) == "DJI_MAVIC_3E"
    assert m3_model_name(1) == "DJI_MAVIC_3T"
    assert m3_model_name(2) == "DJI_MAVIC_3M"


def test_rc_pro_enterprise_identity():
    assert is_rc_pro_enterprise_identity(144, 0)
    assert not is_rc_pro_enterprise_identity(144, 1)
    assert not is_rc_pro_enterprise_identity(77, 0)


def test_validate_m3_scalar_writable_properties():
    assert validate_m3_property_patch(
        {
            "height_limit": 120,
            "night_lights_state": 1,
        }
    ) == {
        "height_limit": 120,
        "night_lights_state": 1,
    }


@pytest.mark.parametrize("value", [19, 1501, True, 120.0, "120"])
def test_height_limit_fails_closed(value):
    with pytest.raises(M3ThingModelValidationError):
        validate_m3_property_patch({"height_limit": value})


def test_obstacle_avoidance_requires_complete_known_struct():
    assert validate_m3_property_patch(
        {
            "obstacle_avoidance": {
                "horizon": 1,
                "upside": 0,
                "downside": 1,
            }
        }
    ) == {
        "obstacle_avoidance": {
            "horizon": 1,
            "upside": 0,
            "downside": 1,
        }
    }

    with pytest.raises(M3ThingModelValidationError, match="requires all directions"):
        validate_m3_property_patch(
            {"obstacle_avoidance": {"horizon": 1}}
        )


def test_camera_watermark_settings_match_dji_constraints():
    patch = validate_m3_property_patch(
        {
            "camera_watermark_settings": {
                "global_enable": 1,
                "drone_type_enable": 1,
                "drone_sn_enable": 1,
                "datetime_enable": 1,
                "gps_enable": 1,
                "user_custom_string_enable": 1,
                "user_custom_string": "M3-Cloud",
                "layout": 3,
            }
        }
    )

    assert patch["camera_watermark_settings"]["user_custom_string"] == "M3-Cloud"
    assert patch["camera_watermark_settings"]["layout"] == 3


def test_watermark_text_limit_is_utf8_bytes_not_characters():
    # 125 two-byte characters are exactly 250 bytes.
    validate_m3_property_patch(
        {
            "camera_watermark_settings": {
                "user_custom_string": "ä" * 125,
            }
        }
    )

    with pytest.raises(M3ThingModelValidationError, match="250 UTF-8 bytes"):
        validate_m3_property_patch(
            {
                "camera_watermark_settings": {
                    "user_custom_string": "ä" * 126,
                }
            }
        )


def test_read_only_or_unknown_properties_are_rejected():
    for name in ("mode_code", "battery", "cameras", "unknown_future_property"):
        with pytest.raises(M3ThingModelValidationError, match="read-only"):
            validate_m3_property_patch({name: 1})
