"""
Storage service — Railway S3-compatible bucket (Tigris).

Folder paths that were used with Cloudinary are preserved as S3 key prefixes.
prefixes so the logical organisation of files stays the same.
"""

import io
import logging
import mimetypes
import uuid
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status

from app.core.bucket_client import get_public_url, get_s3_client
from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── Limits ──────────────────────────────────────────────────────────────────
MAX_IMAGE_SIZE = 10 * 1024 * 1024   # 10 MB
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50 MB

ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm"}

# Content-type map for extensions not always detected by mimetypes
_MIME_OVERRIDE = {
    "webp": "image/webp",
    "webm": "video/webm",
}


def _mime_for_ext(ext: str) -> str:
    return _MIME_OVERRIDE.get(ext) or mimetypes.guess_type(f"file.{ext}")[0] or "application/octet-stream"


class StorageService:
    """
    S3-backed storage service (Railway / Tigris).

    All methods have the same signatures and return the same data types
    (a public HTTPS URL string for uploads, bool for deletes).
    """

    # ── Validation helpers ────────────────────────────────────────────────

    def validate_file_extension(self, filename: str, allowed_extensions: set) -> str:
        """Validate filename extension against allowed set."""
        if not filename or "." not in filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid file format. File must have an extension.",
            )
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext not in allowed_extensions:
            allowed_str = ", ".join(sorted(allowed_extensions))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type '.{ext}'. Allowed types: {allowed_str}.",
            )
        return ext

    def validate_file_size(self, file_bytes: bytes, max_size: int, file_type: str):
        """Validate byte length against size limit."""
        if len(file_bytes) > max_size:
            max_mb = max_size // (1024 * 1024)
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{file_type.capitalize()} file size exceeds maximum limit of {max_mb}MB.",
            )

    # ── Upload helpers ────────────────────────────────────────────────────

    KNOWN_TIGRIS_BUCKET: str = "neat-crate-hruffn9s2hbs2l"

    def _resolve_bucket(self, bucket_name: Optional[str]) -> str:
        """Sanitize and resolve bucket name, correcting aliases and missing hash suffixes."""
        if not bucket_name or not str(bucket_name).strip():
            return self.KNOWN_TIGRIS_BUCKET
        b = str(bucket_name).strip().strip("'\"").rstrip("/")
        if b == "neat-crate" or (b.startswith("neat-crate") and not b.endswith("-hruffn9s2hbs2l")):
            return self.KNOWN_TIGRIS_BUCKET
        if b.lower() in ("chocolate-world", "chovique", "chovique-bucket", "neat_crate"):
            return self.KNOWN_TIGRIS_BUCKET
        return b

    def _save_locally(self, data: bytes, key: str, content_type: str) -> str:
        """
        Resilient local storage fallback when S3/Tigris is unavailable.
        Saves file under static/uploads/{key} and returns public URL.
        """
        from pathlib import Path
        clean_key = key.lstrip("/")
        local_path = Path("static") / "uploads" / clean_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        logger.info("Saved file to local storage fallback: %s (%d bytes)", local_path, len(data))

        backend_url = getattr(settings, "BACKEND_URL", "").rstrip("/")
        prefix = getattr(settings, "API_V1_PREFIX", "/api/v1").rstrip("/")
        if backend_url:
            return f"{backend_url}{prefix}/media/{clean_key}"
        return f"{prefix}/media/{clean_key}"

    def _upload_to_s3(
        self,
        data: bytes,
        key: str,
        content_type: str,
    ) -> str:
        """
        Core S3 put-object call with automatic retry on NoSuchBucket and local fallback.
        """
        target_bucket = self._resolve_bucket(settings.S3_BUCKET_NAME)
        logger.info("Uploading to S3 (Bucket=%s, Key=%s, Size=%d bytes)", target_bucket, key, len(data))

        # Attempt 1: Upload to configured target_bucket
        s3 = get_s3_client()
        try:
            s3.put_object(
                Bucket=target_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
            url = get_public_url(key)
            logger.info("Successfully uploaded to S3 key '%s' in bucket '%s': %s", key, target_bucket, url)
            return url
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            # Attempt 2: If bucket does not exist or access denied, retry with known working Tigris bucket
            if error_code in ("NoSuchBucket", "InvalidBucketName", "AccessDenied") and target_bucket != self.KNOWN_TIGRIS_BUCKET:
                logger.warning(
                    "S3 upload failed with %s for bucket '%s'. Retrying with verified Tigris bucket '%s'...",
                    error_code,
                    target_bucket,
                    self.KNOWN_TIGRIS_BUCKET,
                )
                try:
                    s3.put_object(
                        Bucket=self.KNOWN_TIGRIS_BUCKET,
                        Key=key,
                        Body=data,
                        ContentType=content_type,
                    )
                    url = get_public_url(key)
                    logger.info("Successfully uploaded to fallback S3 bucket '%s', key '%s': %s", self.KNOWN_TIGRIS_BUCKET, key, url)
                    return url
                except Exception as inner_exc:
                    logger.error("Fallback S3 upload to '%s' failed: %s", self.KNOWN_TIGRIS_BUCKET, inner_exc)

            # Attempt 3: Local file storage fallback so user upload never fails with 500
            logger.warning("All S3 upload attempts failed (%s). Saving locally to disk fallback...", exc)
            return self._save_locally(data, key, content_type)
        except Exception as exc:
            logger.warning("S3 upload encountered exception (%s). Saving locally to disk fallback...", exc)
            return self._save_locally(data, key, content_type)

    def _build_key(self, folder: str, filename: str) -> str:
        """
        Construct the S3 object key.

        e.g.  folder='chocolate-world/products', filename='abc.jpg'
              → 'chocolate-world/products/<uuid4>-abc.jpg'

        A UUID prefix avoids collisions between same-named files.
        """
        unique = uuid.uuid4().hex
        # Strip any leading slashes from the folder path
        folder = folder.strip("/")
        return f"{folder}/{unique}-{filename}" if folder else f"{unique}-{filename}"

    # ── Public API ────────────────────────────────────────────────────

    async def upload_image(
        self,
        file: UploadFile,
        folder: str = "chocolate-world/products",
    ) -> str:
        """Validate and upload an image file to S3.  Returns public URL."""
        ext = self.validate_file_extension(file.filename or "", ALLOWED_IMAGE_EXTENSIONS)
        file_bytes = await file.read()
        self.validate_file_size(file_bytes, MAX_IMAGE_SIZE, "image")

        key = self._build_key(folder, file.filename or f"image.{ext}")
        content_type = _mime_for_ext(ext)
        return self._upload_to_s3(file_bytes, key, content_type)

    async def upload_video(
        self,
        file: UploadFile,
        folder: str = "chocolate-world/reels",
    ) -> str:
        """Validate and upload a video file to S3.  Returns public URL."""
        ext = self.validate_file_extension(file.filename or "", ALLOWED_VIDEO_EXTENSIONS)
        file_bytes = await file.read()
        self.validate_file_size(file_bytes, MAX_VIDEO_SIZE, "video")

        key = self._build_key(folder, file.filename or f"video.{ext}")
        content_type = _mime_for_ext(ext)
        return self._upload_to_s3(file_bytes, key, content_type)

    async def upload_bytes(
        self,
        file_bytes: bytes,
        filename: str,
        folder: str = "chocolate-world/invoices",
        resource_type: str = "raw",
    ) -> str:
        """
        Upload raw bytes (e.g. PDF/HTML invoice) to S3.  Returns public URL.

        `resource_type` is accepted for API compatibility but ignored — S3
        does not distinguish between image/video/raw at the API level.
        """
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_type = _mime_for_ext(ext) if ext else "application/octet-stream"
        key = self._build_key(folder, filename)
        return self._upload_to_s3(file_bytes, key, content_type)

    def delete_media(self, public_id: str, resource_type: str = "image") -> bool:
        """
        Delete an object from S3.

        `public_id` may be either:
          • an S3 object key  (e.g.  'chocolate-world/products/abc.jpg')
          • a full public URL (auto-extracted to key)
        """
        key = self._key_from_public_id(public_id)
        if not key:
            logger.warning("delete_media: could not resolve key from '%s'", public_id)
            return False

        clean_key = key.lstrip("/")
        deleted = False

        # 1. Attempt delete from local storage if exists
        try:
            from pathlib import Path
            local_path = Path("static") / "uploads" / clean_key
            if local_path.is_file():
                local_path.unlink(missing_ok=True)
                logger.info("Deleted local storage file: %s", local_path)
                deleted = True
        except Exception as exc:
            logger.warning("Could not delete local file '%s': %s", clean_key, exc)

        # 2. Attempt delete from S3
        s3 = get_s3_client()
        target_bucket = self._resolve_bucket(settings.S3_BUCKET_NAME)
        buckets_to_try = [target_bucket]
        if self.KNOWN_TIGRIS_BUCKET != target_bucket:
            buckets_to_try.append(self.KNOWN_TIGRIS_BUCKET)

        for b in buckets_to_try:
            try:
                s3.delete_object(Bucket=b, Key=clean_key)
                logger.info("Deleted S3 object: %s from bucket %s", clean_key, b)
                deleted = True
                break
            except Exception as exc:
                logger.debug("Failed to delete S3 object '%s' from bucket '%s': %s", clean_key, b, exc)

        return deleted

    # ── URL helpers ────────────────────────────────────────────────

    def extract_public_id(self, url: str) -> Optional[str]:
        """
        Extract the S3 object key from a public URL so it can be deleted.

        Handles:
          - /api/v1/media/{key} or /api/v1/storage/{key}
          - https://{backend}/api/v1/media/{key}
          - Direct S3/Tigris URL (if used)
          - Bare S3 key
        """
        if not url:
            return None
        if "/media/" in url:
            return url.split("/media/", 1)[1]
        if "/storage/" in url:
            return url.split("/storage/", 1)[1]
        
        base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
        if not base:
            endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
            base = f"{endpoint}/{settings.S3_BUCKET_NAME}"
        if url.startswith(base + "/"):
            return url[len(base) + 1:]
        return url

    # ── Internal ──────────────────────────────────────────────────────────

    def _key_from_public_id(self, public_id: str) -> Optional[str]:
        """
        Resolve whatever string was passed to delete_media into an S3 key.
        """
        if not public_id:
            return None

        if "/media/" in public_id:
            return public_id.split("/media/", 1)[1]
        if "/storage/" in public_id:
            return public_id.split("/storage/", 1)[1]

        base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
        if not base:
            endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
            base = f"{endpoint}/{settings.S3_BUCKET_NAME}"

        if public_id.startswith("http://") or public_id.startswith("https://"):
            if public_id.startswith(base + "/"):
                return public_id[len(base) + 1:]
            logger.debug("Skipping non-S3 URL in delete_media: %s", public_id)
            return None

        return public_id

    # ── Backward-compat alias (admin_service calls delete_image too) ──────

    async def delete_image(self, public_id: str) -> bool:
        """Alias for delete_media kept for backward compatibility."""
        return self.delete_media(public_id, resource_type="image")


# Module-level singleton
storage_service = StorageService()
