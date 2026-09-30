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
    Build the permanent public URL stored in PostgreSQL.

    Priority order:
    1. If S3_PUBLIC_BASE_URL is set → use it as a direct CDN/Tigris URL
       (e.g. https://neat-crate-hruffn9s2hbs2l.t3.storageapi.dev)
    2. If BACKEND_URL is set → route through the backend media proxy
       (e.g. https://mybackend.up.railway.app/api/v1/media/<key>)
    3. Last resort → relative URL /api/v1/media/<key>
       (works only when frontend and backend share the same domain)
    """
    clean_key = key.lstrip("/")

    # Option 1: Use the Tigris / S3-compatible CDN public URL directly.
    # This is the correct path when S3_PUBLIC_BASE_URL is configured.
    custom_base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
    if custom_base:
        url = f"{custom_base}/{clean_key}"
        logger.debug("get_public_url → CDN: %s", url)
        return url

    # Option 2: Route through our own backend media proxy (presigned-URL redirect).
    # Requires BACKEND_URL to be set in environment (e.g. on Railway/Render).
    backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
    prefix = getattr(settings, "API_V1_PREFIX", "/api/v1").rstrip("/")

    if backend_url:
        url = f"{backend_url}{prefix}/media/{clean_key}"
        logger.debug("get_public_url → backend proxy: %s", url)
        return url

    # Option 3: Relative URL — only works when frontend & backend are on the same host.
    url = f"{prefix}/media/{clean_key}"
    logger.warning(
        "get_public_url: No S3_PUBLIC_BASE_URL or BACKEND_URL configured. "
        "Returning relative URL '%s' — images will break if frontend and backend "
        "are on different domains. Set BACKEND_URL in your Railway/Render env vars.",
        url,
    )
    return url

