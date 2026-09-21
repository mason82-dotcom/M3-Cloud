import pytest
from fastapi import HTTPException

from app.api_dji import _require_control_token
from app.config import settings


def test_dji_control_api_fails_closed_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "dji_control_api_token", "")

    with pytest.raises(HTTPException) as exc_info:
        _require_control_token(None)

    assert exc_info.value.status_code == 503


def test_dji_control_api_rejects_missing_or_wrong_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "dji_control_api_token", "correct")

    for token in (None, "", "wrong"):
        with pytest.raises(HTTPException) as exc_info:
            _require_control_token(token)
        assert exc_info.value.status_code == 401


def test_dji_control_api_accepts_exact_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "dji_control_api_token", "correct")

    _require_control_token("correct")
