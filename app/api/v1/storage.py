"""
Public storage asset serving endpoint.

Generates presigned GET URLs for objects in the Railway S3 bucket (Tigris)
and redirects the client with HTTP 307. This allows private buckets to serve
public assets (images, videos, invoices) without 403 AccessDenied errors
and without backend proxy bandwidth costs.
"""

import logging
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.storage import get_s3_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage"])


@router.get("/{file_path:path}", summary="Serve public asset from S3 bucket")
async def get_storage_file(file_path: str):
    """
    Serve a file from the S3 bucket via a presigned URL redirect.
    """
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File path is required",
        )

    clean_key = file_path.lstrip("/")

    s3 = get_s3_client()
    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": clean_key},
            ExpiresIn=86400,  # 24 hours
        )
        return RedirectResponse(
            url=presigned_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Cache-Control": "public, max-age=86400",
            },
        )
    except (BotoCoreError, ClientError) as exc:
        logger.error("Failed to generate presigned URL for S3 key '%s': %s", clean_key, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found in storage",
        )
