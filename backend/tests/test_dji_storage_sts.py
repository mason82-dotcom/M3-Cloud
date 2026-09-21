from datetime import datetime, timezone
import json

import pytest

from app.config import Settings
from app.dji.storage_sts import (
    DJIPilotStorageError,
    _pilot_session_policy,
    issue_pilot_sts_credentials,
    pilot_storage_ready,
)


class FakeSTS:
    def __init__(self):
        self.federation_calls = []
        self.assume_calls = []

    def get_federation_token(self, **kwargs):
        self.federation_calls.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "temp-access",
                "SecretAccessKey": "temp-secret",
                "SessionToken": "temp-token",
                "Expiration": datetime.now(timezone.utc),
            }
        }

    def assume_role(self, **kwargs):
        self.assume_calls.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "role-access",
                "SecretAccessKey": "role-secret",
                "SessionToken": "role-token",
                "Expiration": datetime.now(timezone.utc),
            }
        }


def settings(**updates):
    base = Settings(_env_file=None).model_copy(
        update={
            "dji_pilot_storage_endpoint": "http://192.168.178.45:8333",
            "dji_pilot_storage_sts_endpoint": "http://seaweedfs:8333",
            "dji_pilot_storage_provider": "minio",
            "dji_pilot_storage_bucket": "m3-media",
            "dji_pilot_storage_access_key": "master",
            "dji_pilot_storage_secret_key": "master-secret",
            "dji_pilot_storage_sts_mode": "federation_token",
            **updates,
        }
    )
    return base


def test_federation_storage_is_ready_without_role_arn():
    value = settings(dji_pilot_storage_role_arn="")
    assert pilot_storage_ready(value) is True


def test_assume_role_mode_requires_role_arn():
    assert pilot_storage_ready(
        settings(
            dji_pilot_storage_sts_mode="assume_role",
            dji_pilot_storage_role_arn="",
        )
    ) is False
    assert pilot_storage_ready(
        settings(
            dji_pilot_storage_sts_mode="assume_role",
            dji_pilot_storage_role_arn="arn:aws:iam::role/M3CloudPilot2",
        )
    ) is True


def test_federation_policy_is_workspace_scoped():
    policy = _pilot_session_policy(
        bucket="m3-media",
        workspace_id="e3dea0f5-37f2-4d79-ae58-490af3228069",
    )

    encoded = json.dumps(policy)
    assert "arn:aws:s3:::m3-media/pilot2/e3dea0f5-37f2-4d79-ae58-490af3228069/*" in encoded
    assert '"s3:ListBucket"' in encoded
    assert '"s3:prefix"' in encoded
    assert "s3:ListBucketMultipartUploads" not in encoded
    assert "arn:aws:s3:::*" not in encoded


@pytest.mark.parametrize("workspace_id", ["", "../other", "bad*", "a/b"])
def test_federation_policy_rejects_unsafe_workspace_ids(workspace_id):
    with pytest.raises(DJIPilotStorageError):
        _pilot_session_policy(bucket="m3-media", workspace_id=workspace_id)


def test_issue_federation_token_uses_inline_workspace_policy(monkeypatch):
    fake = FakeSTS()
    monkeypatch.setattr(
        "app.dji.storage_sts.boto3.client",
        lambda *args, **kwargs: fake,
    )

    result = issue_pilot_sts_credentials(
        settings(),
        workspace_id="e3dea0f5-37f2-4d79-ae58-490af3228069",
    )

    assert result.object_key_prefix == "pilot2/e3dea0f5-37f2-4d79-ae58-490af3228069"
    assert result.access_key_id == "temp-access"
    assert len(fake.federation_calls) == 1
    assert fake.assume_calls == []

    call = fake.federation_calls[0]
    assert call["Name"] == "m3cloud-pilot2"
    policy = json.loads(call["Policy"])
    object_resource = policy["Statement"][0]["Resource"][0]
    assert object_resource.endswith(
        "/pilot2/e3dea0f5-37f2-4d79-ae58-490af3228069/*"
    )


def test_issue_assume_role_remains_available(monkeypatch):
    fake = FakeSTS()
    monkeypatch.setattr(
        "app.dji.storage_sts.boto3.client",
        lambda *args, **kwargs: fake,
    )

    result = issue_pilot_sts_credentials(
        settings(
            dji_pilot_storage_sts_mode="assume_role",
            dji_pilot_storage_role_arn="arn:aws:iam::role/M3CloudPilot2",
        ),
        workspace_id="e3dea0f5-37f2-4d79-ae58-490af3228069",
    )

    assert result.access_key_id == "role-access"
    assert fake.federation_calls == []
    assert fake.assume_calls[0]["RoleArn"] == "arn:aws:iam::role/M3CloudPilot2"
