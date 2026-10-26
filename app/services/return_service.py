import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.order import Order
from app.models.return_request import ReturnRequest, generate_return_id
from app.models.ticket import SupportTicket
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.repositories.return_request_repository import ReturnRequestRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.notification_repository import NotificationRepository
from app.schemas.return_request import ALLOWED_RETURN_REASONS, SUPPORT_RETURN_STATUSES, ReturnRequestResponse
from app.services.storage_service import storage_service, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_SIZE

logger = logging.getLogger(__name__)

DEFAULT_RETURN_WINDOW_SECONDS = 1800.0  # 30 minutes fallback


def calculate_window_seconds(unit: str, value: int) -> float:
    unit = (unit or "minutes").strip().lower()
    val = max(1, int(value or 30))
    if unit == "minutes":
        return float(val * 60)
    elif unit == "hours":
        return float(val * 3600)
    elif unit == "days":
        return float(val * 86400)
    return float(val * 60)


class ReturnService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.return_repo = ReturnRequestRepository(db)
        self.order_repo = OrderRepository(db)
        self.ticket_repo = TicketRepository(db)
        self.notif_repo = NotificationRepository(db)

    async def get_return_policy(self) -> dict:
        from app.repositories.platform_settings_repository import PlatformSettingsRepository
        settings_repo = PlatformSettingsRepository(self.db)
        settings = await settings_repo.get()

        enabled = getattr(settings, "return_requests_enabled", True)
        if enabled is None:
            enabled = True
        val = getattr(settings, "return_window_value", 30) or 30
        unit = getattr(settings, "return_window_unit", "minutes") or "minutes"
        photo_req = bool(getattr(settings, "return_photo_required", False))
        window_sec = calculate_window_seconds(unit, val)

        return {
            "return_requests_enabled": bool(enabled),
            "return_window_value": int(val),
            "return_window_unit": str(unit),
            "return_window_seconds": float(window_sec),
            "return_photo_required": bool(photo_req),
        }

    async def create_return_request(
        self,
        order_id: str,
        user: User,
        reason: str,
        description: str,
        photo: Optional[UploadFile] = None,
        photo_url: Optional[str] = None,
    ) -> ReturnRequest:
        # Check platform settings for return requests policy
        policy = await self.get_return_policy()
        if not policy["return_requests_enabled"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Return requests are currently unavailable."
            )

        # 1. Fetch Order and verify ownership
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or access denied."
            )

        # 2. Check for duplicate return request or existing return state
        existing = await self.return_repo.get_by_order_id(order.id)
        if existing or str(order.status or "") in ("Returned", "Return Requested"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A return request has already been submitted for this order."
            )

        # 3. Verify order status is 'Delivered'
        if str(order.status or "") != "Delivered":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only delivered orders can be requested for return."
            )

        # 4. Check if refunded
        if str(getattr(order, "payment_status", "") or "").upper() in ("REFUNDED", "PARTIALLY REFUNDED"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This order has already been refunded."
            )

        # 5. Delivery timestamp and dynamic window verification
        delivery_dt = getattr(order, "delivered_at", None)
        if not delivery_dt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order delivery timestamp is missing or invalid."
            )

        now_utc = datetime.now(timezone.utc)
        if delivery_dt.tzinfo is None:
            delivery_dt = delivery_dt.replace(tzinfo=timezone.utc)

        diff_seconds = (now_utc - delivery_dt).total_seconds()
        window_seconds = policy["return_window_seconds"]
        if diff_seconds > window_seconds:
            val = policy["return_window_value"]
            unit = policy["return_window_unit"]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"The return request window has expired. Returns must be submitted within {val} {unit} of delivery."
            )

        # Photo evidence check if mandatory
        has_photo = (photo and hasattr(photo, "filename") and bool(photo.filename)) or bool(photo_url)
        if policy["return_photo_required"] and not has_photo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Photo evidence is required to submit a return request."
            )

        # 6. Validate Return Reason
        clean_reason = (reason or "").strip()
        if not clean_reason or clean_reason not in ALLOWED_RETURN_REASONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid return reason. Must be one of: {', '.join(ALLOWED_RETURN_REASONS)}"
            )

        # 7. Validate Description
        clean_desc = (description or "").strip()
        if not clean_desc or len(clean_desc) < 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Description is required and must be at least 5 characters."
            )

        # 8. Handle Photo Upload with security and size validation (max 5MB)
        final_photo_url = photo_url
        if photo and hasattr(photo, "filename") and photo.filename:
            # Validate extension
            ext = storage_service.validate_file_extension(photo.filename, ALLOWED_IMAGE_EXTENSIONS)
            content = await photo.read()
            # Validate file size (max 5MB)
            if len(content) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Photo file size exceeds the maximum allowed limit of 5MB."
                )

            # Upload to cloud / local storage fallback
            key = storage_service._build_key("chocolate-world/returns", photo.filename)
            from app.services.storage_service import _mime_for_ext
            content_type = _mime_for_ext(ext)
            final_photo_url = storage_service._upload_to_s3(content, key, content_type)

        # 9. Retrieve authoritative database values
        order_amount = float(order.total or 0.0)
        payment_method = str(order.payment_method or "Cash on Delivery")
        delivery_address = order.shipping_address or {}

        # 10. Generate ID and create ReturnRequest
        return_req_id = generate_return_id()
        return_req = ReturnRequest(
            id=return_req_id,
            order_id=order.id,
            customer_id=user.id,
            customer_name=user.full_name or order.shipping_name or "Valued Customer",
            customer_email=user.email,
            customer_phone=user.phone or order.shipping_phone,
            order_amount=order_amount,
            payment_method=payment_method,
            delivery_address=delivery_address,
            delivered_at=delivery_dt,
            reason=clean_reason,
            description=clean_desc,
            photo_url=final_photo_url,
            status="Pending",
        )
        self.db.add(return_req)
        await self.db.flush()

        # 11. Create corresponding SupportTicket to integrate seamlessly with support/admin workflow
        support_ticket = SupportTicket(
            customer_id=user.id,
            customer_name=user.full_name or "Valued Customer",
            category="Return Request",
            description=f"[{clean_reason}] {clean_desc}",
            order_id=order.id,
            status="Pending",
            photo_url=final_photo_url,
            return_request_id=return_req.id,
        )
        self.db.add(support_ticket)
        await self.db.flush()

        # Link ticket to return request
        return_req.ticket_id = support_ticket.id

        # 12. Update order status and return metadata
        order.status = "Return Requested"
        order.returned_at = now_utc
        order.return_reason = clean_reason
        self.db.add(order)

        # 13. Create In-App Notification for customer
        try:
            await self.notif_repo.create(
                user_id=user.id,
                title="Return Request Submitted",
                message=f"Return request #{return_req.id} for Order #{order.id} has been received. Our team will review your request shortly.",
                type="order",
                related_entity_type="return_request",
                related_entity_id=return_req.id,
            )
        except Exception as notif_err:
            logger.warning("Failed to create customer return notification: %s", notif_err)

        # 14. Admin notification
        try:
            from app.services.notification_service import NotificationService
            await NotificationService(self.db).notify_support_message(
                ticket_id=support_ticket.id,
                user_name=user.full_name or "Customer",
                subject=f"Return Request #{return_req.id} ({clean_reason}): Order #{order.id}",
                commit=False,
            )
        except Exception as e:
            logger.warning("Failed to create admin notification for return request: %s", e)

        # 15. Send confirmation email to customer (non-blocking)
        try:
            if user.email:
                from app.integrations.resend import resend_email
                from app.services.customer_service import _format_order_items_html
                returned_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
                items_html = _format_order_items_html(order)
                asyncio.create_task(
                    resend_email.send_return_request(
                        email=user.email,
                        name=user.full_name or "Valued Customer",
                        order_id=order.id,
                        return_requested_at=returned_str,
                        return_reason=clean_reason,
                        return_items_html=items_html,
                    )
                )
        except Exception as e_mail:
            logger.warning("Failed to dispatch return confirmation email: %s", e_mail)

        await self.db.commit()
        await self.db.refresh(return_req)
        return return_req

    async def get_return_request_by_order(
        self, order_id: str, current_user: User
    ) -> Optional[ReturnRequest]:
        return_req = await self.return_repo.get_by_order_id(order_id)
        if not return_req:
            return None

        # Ensure customer can only view their own, unless admin/superadmin
        is_staff = current_user.role in ("admin", "superadmin", "super_admin")
        if not is_staff and return_req.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this return request."
            )
        return return_req

    async def get_return_request_by_id(
        self, return_id: str, current_user: User
    ) -> ReturnRequest:
        return_req = await self.return_repo.get_by_id(return_id)
        if not return_req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Return request not found."
            )

        is_staff = current_user.role in ("admin", "superadmin", "super_admin")
        if not is_staff and return_req.customer_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this return request."
            )
        return return_req

    async def get_user_return_requests(self, user_id: str) -> List[ReturnRequest]:
        return await self.return_repo.get_by_customer_id(user_id)

    async def get_all_return_requests(self) -> List[ReturnRequest]:
        return await self.return_repo.get_all()

    async def update_return_status(
        self,
        return_id: str,
        new_status: str,
        admin_notes: Optional[str] = None,
        admin_user: Optional[User] = None,
    ) -> ReturnRequest:
        return_req = await self.return_repo.get_by_id(return_id)
        if not return_req:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Return request not found."
            )

        clean_status = (new_status or "").strip()
        if clean_status not in SUPPORT_RETURN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status. Must be one of: {', '.join(SUPPORT_RETURN_STATUSES)}"
            )

        return_req.status = clean_status
        if admin_notes is not None:
            return_req.admin_notes = admin_notes

        # Sync linked SupportTicket if exists
        if return_req.ticket_id:
            ticket = await self.ticket_repo.get_by_id(return_req.ticket_id)
            if ticket:
                ticket.status = clean_status
                if admin_notes is not None:
                    ticket.admin_notes = admin_notes
                ticket.status_change_count = (ticket.status_change_count or 0) + 1
                self.db.add(ticket)

        # Update order status based on return decision
        order = await self.order_repo.get_by_id(return_req.order_id)
        if order:
            if clean_status == "Approved":
                order.status = "Returned"
            elif clean_status == "Rejected":
                # Return rejected, remains in Delivered state
                order.status = "Delivered"
            self.db.add(order)

        # Notify customer of status change
        try:
            await self.notif_repo.create(
                user_id=return_req.customer_id,
                title=f"Return Request {clean_status}",
                message=f"Your return request #{return_req.id} for Order #{return_req.order_id} has been marked as '{clean_status}'.",
                type="order",
                related_entity_type="return_request",
                related_entity_id=return_req.id,
            )
        except Exception as e:
            logger.warning("Failed to notify customer of return status update: %s", e)

        # Audit log if admin user provided
        if admin_user:
            try:
                from app.models.audit_log import AuditLog
                audit = AuditLog(
                    user_id=admin_user.id,
                    user_role=admin_user.role,
                    action="UPDATE_RETURN_REQUEST_STATUS",
                    module="returns",
                    entity_type="return_request",
                    entity_id=return_req.id,
                    status="SUCCESS",
                    resource=f"/admin/returns/{return_req.id}/status",
                    details=f"Updated Return #{return_req.id} to '{clean_status}'. Notes: {admin_notes or 'None'}",
                )
                self.db.add(audit)
            except Exception as e:
                logger.warning("Failed to write audit log for return status update: %s", e)

        await self.db.commit()
        await self.db.refresh(return_req)
        return return_req
