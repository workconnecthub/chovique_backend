"""
S3-compatible storage client factory (Railway / Tigris).

Returns a configured boto3 S3 client that talks to the Railway bucket.
All upload/delete logic lives in app.services.storage_service.
the rest of the codebase needs zero changes.
"""

import boto3
from botocore.config import Config

from app.core.config import settings

_s3_client = None


def get_s3_client():
    """Return a (lazily created, module-level singleton) boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            region_name=settings.S3_REGION,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


def get_public_url(key: str) -> str:
    """
    Build the public HTTPS URL for an object stored in the bucket.

    If S3_PUBLIC_BASE_URL is set in .env that value is used directly.
    Otherwise we derive it from the endpoint URL + bucket name.

    Railway / Tigris public URLs look like:
        https://<bucket>.t3.storageapi.dev/<key>
    """
    base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    if not base:
        # Derive: strip trailing slash from endpoint, append bucket name
        endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
        base = f"{endpoint}/{settings.S3_BUCKET_NAME}"
    return f"{base}/{key}"
