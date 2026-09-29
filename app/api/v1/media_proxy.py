"""
Public media delivery proxy endpoint.

Serves images, videos, and documents stored in the private Railway S3 bucket (Tigris).
When a browser requests an asset via <img src="..."/>, this endpoint generates
a secure, time-limited presigned GET URL and redirects the browser (HTTP 307).

Benefits:
- Private bucket security maintained.
- Browser caches the media directly.
- Free data egress (Railway S3 Tigris has free egress).
- No backend bandwidth consumption.
"""

import logging
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.bucket_client import get_s3_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Media Proxy"])


@router.get("/media/{file_path:path}", summary="Serve public media asset from Railway bucket")
@router.get("/storage/{file_path:path}", summary="Serve public media asset (storage alias)", include_in_schema=False)
async def serve_media_asset(file_path: str):
    """
    Public access endpoint for Railway bucket assets.
    Redirects to a 24-hour presigned URL with caching headers.
    """
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file path is required",
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
        logger.error("Failed to generate presigned URL for media key '%s': %s", clean_key, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file not found in bucket",
        )
