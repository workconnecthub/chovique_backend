"""Service layer for Superadmin Platform Settings."""

import logging
from fastapi import HTTPException, Request, status

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.audit_log import AuditLog
from app.repositories.platform_settings_repository import PlatformSettingsRepository
from app.schemas.platform_settings import (
    PlatformSettingsUpdateRequest,
    PlatformSettingsResponse,
    MaintenanceModeRequest,
    MaintenanceModeResponse,
)
from app.services.superadmin_notification_service import create_platform_notification

logger = logging.getLogger(__name__)


class PlatformSettingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.repo = PlatformSettingsRepository(db)

    async def get_settings(self) -> PlatformSettingsResponse:
        """Return the current platform settings."""
        row = await self.repo.get()
        return PlatformSettingsResponse.model_validate(row)

    async def update_settings(
        self,
        payload: PlatformSettingsUpdateRequest,
        current_user: User,
        request: Request | None = None,
    ) -> PlatformSettingsResponse:
        """Update all platform settings and log the action."""
        data = payload.model_dump()
        data["updated_by"] = current_user.id

        row = await self.repo.update(data)

        # Audit log
        await self._audit(
            action="PLATFORM_SETTINGS_UPDATED",
            current_user=current_user,
            request=request,
            metadata={"updated_fields": list(data.keys())},
        )

        # Superadmin Notification
        await create_platform_notification(
            db=self.db,
            title="Platform Settings Updated",
            message=f"Global platform configuration updated by {current_user.full_name}.",
            severity="INFO",
            related_entity_type="platform_settings",
            related_entity_id="singleton",
            related_user_id=current_user.id,
        )

        return PlatformSettingsResponse.model_validate(row)

    async def toggle_maintenance_mode(
        self,
        payload: MaintenanceModeRequest,
        current_user: User,
        request: Request | None = None,
    ) -> MaintenanceModeResponse:
        """Enable or disable maintenance mode (requires explicit confirmation)."""
        row = await self.repo.update({
            "maintenance_mode": payload.enable,
            "updated_by": current_user.id,
        })

        action = "MAINTENANCE_MODE_ENABLED" if payload.enable else "MAINTENANCE_MODE_DISABLED"
        await self._audit(
            action=action,
            current_user=current_user,
            request=request,
            metadata={"maintenance_mode": payload.enable},
        )

        verb = "enabled" if payload.enable else "disabled"

        # Superadmin Notification
        await create_platform_notification(
            db=self.db,
            title=f"Maintenance Mode {verb.capitalize()}",
            message=f"Storefront maintenance mode was {verb} by {current_user.full_name}.",
            severity="CRITICAL" if payload.enable else "INFO",
            related_entity_type="platform_settings",
            related_entity_id="singleton",
            related_user_id=current_user.id,
        )
        return MaintenanceModeResponse(
            maintenance_mode=row.maintenance_mode,
            message=f"Maintenance mode {verb} successfully.",
        )

    async def reset_settings(
        self,
        current_user: User,
        request: Request | None = None,
    ) -> PlatformSettingsResponse:
        """Reset all platform settings to safe defaults."""
        from app.models.platform_settings import PlatformSettings

        defaults = {
            "store_front_name": "Chovique Luxury Chocolates",
            "support_email": "support@chovique.com",
            "support_phone": "+91 83098 54870",
            "store_address": "",
            "city": "",
            "state": "",
            "country": "India",
            "pincode": "",
            "base_currency": "INR",
            "timezone": "Asia/Kolkata",
            "business_status": "active",
            "cod_enabled": True,
            "gst_rate": 18.0,
            "platform_fee": 0.0,
            "standard_shipping_charge": 50.0,
            "free_shipping_min_order": 500.0,
            "maximum_cod_order_value": 5000.0,
            "customer_registration_enabled": True,
            "guest_checkout_enabled": True,
            "minimum_order_value": 100.0,
            "order_cancellation_enabled": True,
            "cancellation_time_limit": 24,
            "return_refund_enabled": True,
            "return_requests_enabled": True,
            "return_window_value": 30,
            "return_window_unit": "minutes",
            "return_photo_required": False,
            "maintenance_mode": False,
            "admin_session_timeout": 60,
            "max_login_attempts": 5,
            "account_lockout_duration": 30,
            "updated_by": current_user.id,
        }

        row = await self.repo.update(defaults)

        await self._audit(
            action="PLATFORM_SETTINGS_RESET",
            current_user=current_user,
            request=request,
            metadata={"reset_to": "defaults"},
        )

        return PlatformSettingsResponse.model_validate(row)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _audit(
        self,
        action: str,
        current_user: User,
        request: Request | None,
        metadata: dict | None = None,
    ) -> None:
        try:
            ip = None
            if request:
                forwarded = request.headers.get("X-Forwarded-For")
                ip = forwarded.split(",")[0].strip() if forwarded else (
                    request.client.host if request.client else None
                )

            log_entry = AuditLog(
                user_id=current_user.id,
                user_role=current_user.role,
                action=action,
                module="Platform Settings",
                entity_type="platform_settings",
                entity_id="singleton",
                ip_address=ip,
                request_method=request.method if request else "PUT",
                endpoint=str(request.url) if request else "/api/v1/superadmin/platform-settings",
                status="SUCCESS",
                log_metadata=metadata,
            )
            self.db.add(log_entry)
            await self.db.commit()
        except Exception as exc:
            logger.error("Failed to write audit log for %s: %s", action, exc)
