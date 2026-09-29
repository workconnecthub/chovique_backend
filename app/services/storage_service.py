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

from app.core.storage import get_public_url, get_s3_client
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

    def _upload_to_s3(
        self,
        data: bytes,
        key: str,
        content_type: str,
    ) -> str:
        """
        Core S3 put-object call.  Returns the public URL of the uploaded object.
        Objects are stored with public-read ACL so the URLs can be served directly.
        """
        s3 = get_s3_client()
        try:
            s3.put_object(
                Bucket=settings.S3_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=content_type,
                # Make the object publicly readable
                ACL="public-read",
            )
            url = get_public_url(key)
            logger.info("Uploaded to S3 key '%s': %s", key, url)
            return url
        except (BotoCoreError, ClientError) as exc:
            logger.error("S3 upload failed for key '%s': %s", key, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to upload file to storage: {exc}",
            )

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

        s3 = get_s3_client()
        try:
            s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            logger.info("Deleted S3 object: %s", key)
            return True
        except (BotoCoreError, ClientError) as exc:
            logger.error("Failed to delete S3 object '%s': %s", key, exc)
            return False

    # ── URL helpers ────────────────────────────────────────────────

    def extract_public_id(self, url: str) -> Optional[str]:
        """
        Extract the S3 object key from a public URL so it can be deleted.

        For old Cloudinary URLs (if any exist in DB), extracts the S3 key.
        URL itself (delete_media will handle the extraction).
        For new S3 URLs the key is everything after the bucket path prefix.
        """
        if not url:
            return None
        # New S3 URL — strip base prefix
        base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
        if not base:
            endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
            base = f"{endpoint}/{settings.S3_BUCKET_NAME}"
        if url.startswith(base + "/"):
            return url[len(base) + 1:]
        # Fallback: return the URL as-is; _key_from_public_id handles it
        return url

    # ── Internal ──────────────────────────────────────────────────────────

    def _key_from_public_id(self, public_id: str) -> Optional[str]:
        """
        Resolve whatever string was passed to delete_media into an S3 key.

        Handles:
          1. Already a plain S3 key  ('chocolate-world/products/abc.jpg')
          2. Full public URL built by get_public_url()
          3. Old Cloudinary public IDs — skipped gracefully
        """
        if not public_id:
            return None

        # Strip base URL prefix if present
        base = settings.S3_PUBLIC_BASE_URL.rstrip("/")
        if not base:
            endpoint = settings.S3_ENDPOINT_URL.rstrip("/")
            base = f"{endpoint}/{settings.S3_BUCKET_NAME}"

        if public_id.startswith("http://") or public_id.startswith("https://"):
            if public_id.startswith(base + "/"):
                return public_id[len(base) + 1:]
            # URL from a different provider (old data) — skip gracefully
            logger.debug("Skipping non-S3 URL in delete_media: %s", public_id)
            return None

        # Already a bare key
        return public_id

    # ── Backward-compat alias (admin_service calls delete_image too) ──────

    async def delete_image(self, public_id: str) -> bool:
        """Alias for delete_media kept for backward compatibility."""
        return self.delete_media(public_id, resource_type="image")


# Module-level singleton
storage_service = StorageService()
