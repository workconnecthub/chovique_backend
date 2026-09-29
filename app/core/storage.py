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
    Build the public URL for an object stored in the bucket.

    Because Railway S3 buckets (Tigris) are private by default and direct
    GET requests return 403 Forbidden, we route asset access through the
    backend storage endpoint `/api/v1/storage/{key}`.
    This endpoint redirects to a time-limited presigned URL, allowing
    browsers to load images and media smoothly without auth issues.
    """
    clean_key = key.lstrip("/")

    custom_base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    if custom_base and not ("storageapi.dev" in custom_base):
        return f"{custom_base}/{clean_key}"

    backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
    prefix = getattr(settings, "API_V1_PREFIX", "/api/v1").rstrip("/")
    if backend_url:
        return f"{backend_url}{prefix}/storage/{clean_key}"
    return f"{prefix}/storage/{clean_key}"

