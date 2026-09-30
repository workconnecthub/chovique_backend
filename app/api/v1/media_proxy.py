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
import mimetypes
from pathlib import Path
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings
from app.core.bucket_client import get_s3_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Media Proxy"])


@router.get("/media/{file_path:path}", summary="Serve public media asset from Railway bucket")
@router.get("/storage/{file_path:path}", summary="Serve public media asset (storage alias)", include_in_schema=False)
async def serve_media_asset(file_path: str):
    """
    Public access endpoint for media assets.
    If stored locally in static/uploads, serves it directly.
    Otherwise redirects to a 24-hour presigned S3/Tigris URL with caching headers.
    """
    if not file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media file path is required",
        )

    clean_key = file_path.lstrip("/")

    # 1. Check local static storage fallback
    local_path = Path("static") / "uploads" / clean_key
    if local_path.is_file():
        mime_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        return FileResponse(
            str(local_path),
            media_type=mime_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # 2. Resolve S3 bucket name
    target_bucket = getattr(settings, "S3_BUCKET_NAME", None) or "neat-crate-hruffn9s2hbs2l"
    if target_bucket == "neat-crate" or (target_bucket.startswith("neat-crate") and not target_bucket.endswith("-hruffn9s2hbs2l")):
        target_bucket = "neat-crate-hruffn9s2hbs2l"
    if target_bucket.lower() in ("chocolate-world", "chovique", "chovique-bucket", "neat_crate"):
        target_bucket = "neat-crate-hruffn9s2hbs2l"

    s3 = get_s3_client()
    try:
        presigned_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": target_bucket, "Key": clean_key},
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
