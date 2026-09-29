"""
S3-compatible bucket client factory for Railway (Tigris).

Provides:
- get_s3_client(): Returns a singleton boto3 client configured with Railway S3 credentials.
- get_public_url(key): Builds the public URL to be stored in the PostgreSQL database.
"""

import logging
import boto3
from botocore.config import Config

from app.core.config import settings

logger = logging.getLogger(__name__)

_s3_client = None


def get_s3_client():
    """Return a lazily created, singleton boto3 S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or "https://t3.storageapi.dev",
            region_name=settings.S3_REGION or "auto",
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            config=Config(signature_version="s3v4"),
        )
    return _s3_client


def get_public_url(key: str) -> str:
    """
    Build the permanent public URL to store in the PostgreSQL database.

    Just like Cloudinary stored full URLs (https://res.cloudinary.com/...),
    this generates a public URL pointing to the media endpoint:
      https://<your-backend-domain>/api/v1/media/<key>
    
    When loaded by the frontend (<img src="...">), the media proxy
    seamlessly streams/redirects to the private Railway S3 bucket.
    """
    clean_key = key.lstrip("/")

    # If a custom external CDN / proxy domain is configured:
    custom_base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    if custom_base and not ("storageapi.dev" in custom_base):
        return f"{custom_base}/{clean_key}"

    # Build the URL through our media endpoint
    backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
    prefix = getattr(settings, "API_V1_PREFIX", "/api/v1").rstrip("/")

    if backend_url:
        return f"{backend_url}{prefix}/media/{clean_key}"
    return f"{prefix}/media/{clean_key}"
