from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import Any

import boto3
from botocore.config import Config

from app.config import Settings


class DJIPilotStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class DJIPilotStorageCredentials:
    bucket: str
    endpoint: str
    provider: str
    region: str
    object_key_prefix: str
    access_key_id: str
    access_key_secret: str
    security_token: str
    expire: int

    def as_dji_response(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "credentials": {
                "access_key_id": self.access_key_id,
                "access_key_secret": self.access_key_secret,
                "expire": self.expire,
                "security_token": self.security_token,
            },
            "endpoint": self.endpoint,
            "object_key_prefix": self.object_key_prefix,
            "provider": self.provider,
            "region": self.region,
        }


def pilot_object_key_allowed(workspace_id: str, object_key: str) -> bool:
    path = PurePosixPath(object_key)
    if ".." in path.parts:
        return False
    expected = PurePosixPath("pilot2", workspace_id)
    return path.parts[: len(expected.parts)] == expected.parts


def presign_pilot_object(
    settings: Settings,
    *,
    bucket: str,
    object_key: str,
    expires_in: int = 900,
) -> str:
    endpoint = settings.dji_pilot_storage_endpoint.strip()
    if not endpoint.startswith(("http://", "https://")):
        raise DJIPilotStorageError("DJI Pilot external storage endpoint is not configured")

    access_key = (
        settings.dji_pilot_storage_access_key.strip()
        or settings.s3_access_key.strip()
    )
    secret_key = (
        settings.dji_pilot_storage_secret_key.strip()
        or settings.s3_secret_key.strip()
    )
    if not access_key or not secret_key:
        raise DJIPilotStorageError("DJI Pilot storage signing credentials are missing")

    region = settings.dji_pilot_storage_region.strip() or "us-east-1"
    # Presigning does not contact the endpoint. Use the RC-reachable hostname in
    # the canonical request so the signature remains valid when Pilot 2 follows it.
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        ),
    )
    return str(
        client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=max(60, min(3600, int(expires_in))),
        )
    )


def _sts_mode(settings: Settings) -> str:
    return settings.dji_pilot_storage_sts_mode.strip().lower()


def _pilot_session_policy(
    *,
    bucket: str,
    workspace_id: str,
) -> dict[str, Any]:
    if not bucket or any(token in bucket for token in ("*", "?", "[", "]")):
        raise DJIPilotStorageError("DJI Pilot storage bucket is invalid")
    if (
        not workspace_id
        or "/" in workspace_id
        or any(token in workspace_id for token in ("*", "?", "[", "]"))
    ):
        raise DJIPilotStorageError("DJI Pilot workspace id is invalid for storage policy")

    prefix = f"pilot2/{workspace_id}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}/{prefix}/*",
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                ],
                "Condition": {
                    "StringLike": {
                        "s3:prefix": [
                            prefix,
                            f"{prefix}/*",
                        ],
                    },
                },
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetBucketLocation",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                ],
            },
        ],
    }


def _pilot_storage_ready_for(
    settings: Settings,
    *,
    providers: set[str],
) -> bool:
    endpoint = settings.dji_pilot_storage_endpoint.strip()
    provider = settings.dji_pilot_storage_provider.strip().lower()
    mode = _sts_mode(settings)
    base_ready = bool(
        endpoint.startswith(("http://", "https://"))
        and provider in providers
    )
    if not base_ready:
        return False
    if mode == "federation_token":
        return True
    if mode == "assume_role":
        return bool(settings.dji_pilot_storage_role_arn.strip())
    return False


def pilot_storage_ready(settings: Settings) -> bool:
    """Storage readiness for DJI Pilot media management.

    DJI documents MinIO, AWS S3 and Aliyun OSS for Pilot media uploads.
    """

    return _pilot_storage_ready_for(
        settings,
        providers={"minio", "aws", "ali"},
    )


def pilot_wayline_storage_ready(settings: Settings) -> bool:
    """Storage readiness for DJI Pilot wayline library uploads.

    DJI's Pilot wayline STS contract currently documents only AWS S3 and
    Aliyun OSS providers. Do not advertise the mission component for MinIO.
    """

    return _pilot_storage_ready_for(
        settings,
        providers={"aws", "ali"},
    )


def create_pilot_storage_client(settings: Settings):
    endpoint = (
        settings.dji_pilot_storage_sts_endpoint.strip()
        or settings.s3_endpoint.strip()
    )
    access_key = (
        settings.dji_pilot_storage_access_key.strip()
        or settings.s3_access_key.strip()
    )
    secret_key = (
        settings.dji_pilot_storage_secret_key.strip()
        or settings.s3_secret_key.strip()
    )
    region = settings.dji_pilot_storage_region.strip() or "us-east-1"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4"),
    )


def issue_pilot_sts_credentials(
    settings: Settings,
    *,
    workspace_id: str,
) -> DJIPilotStorageCredentials:
    if not pilot_storage_ready(settings):
        raise DJIPilotStorageError("DJI Pilot storage STS is not configured")

    endpoint = settings.dji_pilot_storage_endpoint.strip()
    sts_endpoint = (
        settings.dji_pilot_storage_sts_endpoint.strip()
        or settings.s3_endpoint.strip()
    )
    access_key = (
        settings.dji_pilot_storage_access_key.strip()
        or settings.s3_access_key.strip()
    )
    secret_key = (
        settings.dji_pilot_storage_secret_key.strip()
        or settings.s3_secret_key.strip()
    )
    if not sts_endpoint.startswith(("http://", "https://")):
        raise DJIPilotStorageError("DJI Pilot STS endpoint must be HTTP(S)")
    if not access_key or not secret_key:
        raise DJIPilotStorageError("DJI Pilot STS master credentials are missing")

    duration = max(
        900,
        min(43200, int(settings.dji_pilot_storage_sts_duration_seconds)),
    )
    region = settings.dji_pilot_storage_region.strip() or "us-east-1"

    client = boto3.client(
        "sts",
        endpoint_url=sts_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="v4"),
    )
    mode = _sts_mode(settings)
    bucket = settings.dji_pilot_storage_bucket.strip() or "m3-media"
    try:
        if mode == "federation_token":
            response = client.get_federation_token(
                Name="m3cloud-pilot2",
                DurationSeconds=duration,
                Policy=json.dumps(
                    _pilot_session_policy(
                        bucket=bucket,
                        workspace_id=workspace_id,
                    ),
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        elif mode == "assume_role":
            role_arn = settings.dji_pilot_storage_role_arn.strip()
            if not role_arn:
                raise DJIPilotStorageError(
                    "DJI Pilot AssumeRole mode requires a storage role ARN"
                )
            response = client.assume_role(
                RoleArn=role_arn,
                RoleSessionName="m3cloud-pilot2",
                DurationSeconds=duration,
            )
        else:
            raise DJIPilotStorageError(
                f"Unsupported DJI Pilot storage STS mode: {mode!r}"
            )
    except DJIPilotStorageError:
        raise
    except Exception as exc:
        raise DJIPilotStorageError(
            f"Unable to obtain DJI Pilot storage credentials: {exc}"
        ) from exc

    credentials = response.get("Credentials")
    if not isinstance(credentials, dict):
        raise DJIPilotStorageError("STS response contains no Credentials")

    access_key_id = credentials.get("AccessKeyId")
    access_key_secret = credentials.get("SecretAccessKey")
    security_token = credentials.get("SessionToken")
    if not all(
        isinstance(value, str) and value
        for value in (access_key_id, access_key_secret, security_token)
    ):
        raise DJIPilotStorageError("STS response contains incomplete credentials")

    return DJIPilotStorageCredentials(
        bucket=bucket,
        endpoint=endpoint,
        provider=settings.dji_pilot_storage_provider.strip().lower(),
        region=region,
        object_key_prefix=f"pilot2/{workspace_id}",
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        security_token=security_token,
        expire=duration,
    )
