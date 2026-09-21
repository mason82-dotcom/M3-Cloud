from __future__ import annotations

from dataclasses import dataclass
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


def pilot_storage_ready(settings: Settings) -> bool:
    endpoint = settings.dji_pilot_storage_endpoint.strip()
    role_arn = settings.dji_pilot_storage_role_arn.strip()
    provider = settings.dji_pilot_storage_provider.strip().lower()
    return bool(
        endpoint.startswith(("http://", "https://"))
        and role_arn
        and provider in {"minio", "aws", "ali"}
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
    try:
        response = client.assume_role(
            RoleArn=settings.dji_pilot_storage_role_arn.strip(),
            RoleSessionName="m3cloud-pilot2",
            DurationSeconds=duration,
        )
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
        bucket=settings.dji_pilot_storage_bucket.strip() or "m3-media",
        endpoint=endpoint,
        provider=settings.dji_pilot_storage_provider.strip().lower(),
        region=region,
        object_key_prefix=f"pilot2/{workspace_id}",
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        security_token=security_token,
        expire=duration,
    )
