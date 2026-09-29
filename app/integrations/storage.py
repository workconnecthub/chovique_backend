"""
Storage integration — Railway S3-compatible bucket (Tigris).

Provides a single import point for the storage service used throughout the app.
"""
from app.services.storage_service import storage_service, StorageService

__all__ = ["storage_service", "StorageService"]
