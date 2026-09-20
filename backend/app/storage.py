import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.config import settings


def create_storage_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )


REQUIRED_BUCKETS = ("m3-media", "m3-waylines", "m3-results")


def ensure_storage_buckets(client: BaseClient | None = None) -> list[str]:
    """Create the required S3 buckets if they do not already exist."""
    storage_client = client or create_storage_client()
    existing = {
        bucket["Name"]
        for bucket in storage_client.list_buckets().get("Buckets", [])
    }
    created: list[str] = []
    for bucket in REQUIRED_BUCKETS:
        if bucket not in existing:
            storage_client.create_bucket(Bucket=bucket)
            created.append(bucket)
    return created
