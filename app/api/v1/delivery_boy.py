"""
Delivery Boy Panel API
======================
Endpoints for the delivery-boy role:
  - GET  /delivery-boy/profile            → own profile
  - GET  /delivery-boy/orders             → assigned orders
  - POST /delivery-boy/orders/{id}/accept → accept assignment
  - POST /delivery-boy/orders/{id}/reject → reject assignment
  - POST /delivery-boy/orders/{id}/picked → mark picked up from store
  - POST /delivery-boy/orders/{id}/out-for-delivery → mark out-for-delivery + generate customer OTP
  - POST /delivery-boy/orders/{id}/deliver → verify OTP + mark delivered

Admin delivery-boy management (require admin/superadmin):
  - GET  /admin/delivery-boys             → list delivery boys
  - POST /admin/delivery-boys             → create delivery boy account
  - PUT  /admin/delivery-boys/{id}        → update delivery boy
  - DELETE /admin/delivery-boys/{id}      → deactivate delivery boy
  - POST /admin/orders/{id}/assign-delivery-boy → assign order
  - POST /admin/orders/{id}/unassign-delivery-boy → unassign order
"""

import logging
import math
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.core.security import hash_password
from app.models.delivery_location import DeliveryPersonLocation
from app.models.order import Order
from app.models.user import User
from app.schemas.order import OrderResponse
from app.services.activity_log_service import log_admin_activity

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/delivery-boy", tags=["Delivery Boy"])
admin_router = APIRouter(prefix="/admin", tags=["Admin – Delivery Management"])


# ─── Helpers ────────────────────────────────────────────────────────────────

def _require_delivery_boy(current_user: User) -> User:
    if current_user.role not in ("delivery_boy", "admin", "superadmin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery account required. Please log in with a delivery executive or store manager account.",
        )
    return current_user


def _generate_delivery_otp() -> str:
    """6-digit numeric OTP."""
    return str(random.randint(100000, 999999))


def _order_to_response(order: Order) -> dict:
    """Serialize an Order ORM object to a dict compatible with OrderResponse."""
    from app.schemas.order import OrderItemResponse, ShippingAddressSchema

    # Build shipping address from snapshot fields (authoritative)
    sa = order.shipping_address or {}
    if isinstance(sa, dict):
        shipping_addr = ShippingAddressSchema(
            name=sa.get("name") or order.shipping_name or "",
            street=sa.get("street") or order.shipping_street or "",
            city=sa.get("city") or order.shipping_city or "",
            state=sa.get("state") or order.shipping_state or "",
            zip=sa.get("zip") or order.shipping_pincode or "",
            phone=sa.get("phone") or order.shipping_phone or "",
            house_number=sa.get("house_number") or order.shipping_house_number,
            area=sa.get("area") or order.shipping_area,
            landmark=sa.get("landmark") or order.shipping_landmark,
            latitude=sa.get("latitude") or order.shipping_latitude,
            longitude=sa.get("longitude") or order.shipping_longitude,
            formatted_address=sa.get("formatted_address") or order.shipping_formatted_address,
        )
    else:
        shipping_addr = ShippingAddressSchema(
            name=order.shipping_name or "",
            street=order.shipping_street or "",
            city=order.shipping_city or "",
            state=order.shipping_state or "",
            zip=order.shipping_pincode or "",
            phone=order.shipping_phone or "",
            house_number=order.shipping_house_number,
            area=order.shipping_area,
            landmark=order.shipping_landmark,
            latitude=order.shipping_latitude,
            longitude=order.shipping_longitude,
            formatted_address=order.shipping_formatted_address,
        )

    customer_name = None
    customer_phone = None
    if order.user:
        customer_name = order.user.full_name
        customer_phone = order.user.phone

    delivery_boy_name = None
    if order.delivery_boy:
        delivery_boy_name = order.delivery_boy.full_name

    store_name = None
    if order.store_location:
        store_name = order.store_location.name

    items = []
    for item in (order.items or []):
        items.append(
            OrderItemResponse(
                product=item.product,
                quantity=item.quantity,
                price=item.price,
            )
        )

    return OrderResponse(
        id=order.id,
        items=items,
        total=order.total,
        subtotal=order.subtotal,
        discount=order.discount,
        coupon_code=order.coupon_code,
        coupon_discount=order.coupon_discount or 0.0,
        coins_used=order.coins_used or 0,
        coin_discount=order.coin_discount or 0.0,
        coins_earned=order.coins_earned or 0,
        shipping=order.shipping,
        tax=order.tax or 0.0,
        date=order.created_at.isoformat() if order.created_at else "",
        status=order.status,
        payment_status=order.payment_status or "PENDING",
        shippingAddress=shipping_addr,
        shipping_address=shipping_addr,
        deliveryOption=order.delivery_option or "Standard Delivery",
        paymentMethod=order.payment_method or "UPI",
        fulfillment_type=order.fulfillment_type,
        shipping_provider=order.shipping_provider,
        fulfillment_status=order.fulfillment_status,
        delivery_boy_id=order.delivery_boy_id,
        delivery_boy_name=delivery_boy_name,
        store_location_id=order.store_location_id,
        store_name=store_name,
        invoice_url=order.invoice_url,
        user_id=order.user_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        is_cancellable=False,
        is_returnable=False,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        # Delivery OTP
        delivery_otp=order.delivery_otp,
        delivery_otp_expires_at=order.delivery_otp_expires_at,
        delivery_accepted_at=order.delivery_accepted_at,
        delivery_rejected_at=order.delivery_rejected_at,
        delivery_rejection_reason=order.delivery_rejection_reason,
        delivery_picked_at=order.delivery_picked_at,
        # Snapshot fields
        shipping_name=order.shipping_name,
        shipping_phone=order.shipping_phone,
        shipping_house_number=order.shipping_house_number,
        shipping_street=order.shipping_street,
        shipping_area=order.shipping_area,
        shipping_landmark=order.shipping_landmark,
        shipping_city=order.shipping_city,
        shipping_district=order.shipping_district,
        shipping_state=order.shipping_state,
        shipping_pincode=order.shipping_pincode,
        shipping_latitude=order.shipping_latitude,
        shipping_longitude=order.shipping_longitude,
        shipping_formatted_address=order.shipping_formatted_address,
        shipping_location_verified=order.shipping_location_verified,
    )


# ─── Pydantic schemas ────────────────────────────────────────────────────────

class RejectOrderPayload(BaseModel):
    reason: Optional[str] = None


class BatchAcceptPayload(BaseModel):
    order_ids: Optional[List[str]] = None


class VerifyDeliveryOTPPayload(BaseModel):
    otp: str


class CreateDeliveryBoyRequest(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    password: str

    @field_validator("password")
    @classmethod
    def _strong_password(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters.")
        return v


class UpdateDeliveryBoyRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class AssignDeliveryBoyPayload(BaseModel):
    delivery_boy_id: str


class DeliveryBoyProfileResponse(BaseModel):
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    is_active: bool
    role: str
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DeliveryBoyListItem(BaseModel):
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    is_active: bool
    role: str
    avatar_url: Optional[str] = None
    created_at: Optional[datetime] = None
    active_orders: int = 0

    class Config:
        from_attributes = True


# ══════════════════════════════════════════════════════════════════════════════
# DELIVERY BOY ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


class UpdateDeliveryBoySelfProfileRequest(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    password: Optional[str] = None


@router.get(
    "/profile",
    response_model=DeliveryBoyProfileResponse,
    summary="Get own delivery boy profile",
)
async def get_delivery_profile(
    current_user: User = Depends(get_current_user),
):
    _require_delivery_boy(current_user)
    return current_user


@router.put(
    "/profile",
    response_model=DeliveryBoyProfileResponse,
    summary="Update delivery executive profile details",
)
async def update_delivery_self_profile(
    payload: UpdateDeliveryBoySelfProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if payload.full_name is not None and payload.full_name.strip():
        current_user.full_name = payload.full_name.strip()
    if payload.phone is not None:
        current_user.phone = payload.phone.strip() or None
    if payload.avatar_url is not None:
        current_user.avatar_url = payload.avatar_url.strip() or None
    if payload.password:
        if len(payload.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        current_user.hashed_password = hash_password(payload.password)

    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.post(
    "/profile/avatar",
    summary="Upload avatar photo for delivery executive",
)
async def upload_delivery_avatar(
    avatar: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)
    from app.services.customer_service import CustomerService

    allowed_mimes = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    filename = avatar.filename or ""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if (avatar.content_type and avatar.content_type.lower() not in allowed_mimes) and ext not in ["jpg", "jpeg", "png", "webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image format. Only JPG, JPEG, PNG, and WebP formats are allowed.",
        )

    service = CustomerService(db)
    res = await service.upload_avatar(current_user.id, avatar)
    current_user.avatar_url = res.avatar_url
    await db.commit()
    await db.refresh(current_user)
    return {"avatar_url": res.avatar_url, "message": "Avatar uploaded successfully."}


@router.get(
    "/orders",
    summary="Get orders assigned to this delivery boy",
)
async def get_assigned_orders(
    status_filter: Optional[str] = Query(None, description="Filter by fulfillment_status"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        # Supervisor mode: if orders are assigned specifically to admin user, return those;
        # otherwise return all assigned or active fulfillment orders so the admin can supervise/test fleet operations.
        admin_assigned_count = await db.scalar(
            select(func.count(Order.id)).where(Order.delivery_boy_id == current_user.id)
        )
        if admin_assigned_count and admin_assigned_count > 0:
            stmt = select(Order).where(Order.delivery_boy_id == current_user.id)
            if status_filter:
                stmt = stmt.where(Order.fulfillment_status == status_filter.upper())
        else:
            stmt = select(Order)
            if status_filter:
                stmt = stmt.where(Order.fulfillment_status == status_filter.upper())
            else:
                # Prioritize active delivery fulfillment orders or orders with assigned delivery boys
                stmt = stmt.where(
                    (Order.delivery_boy_id.isnot(None))
                    | (Order.fulfillment_status.in_(["ASSIGNED", "ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY", "DELIVERED"]))
                )
        result = await db.execute(stmt.order_by(Order.created_at.desc()).limit(50))
        orders = result.scalars().all()
        # Fallback if no delivery-specific orders exist yet in test environment: show latest orders
        if not orders and not status_filter:
            recent_res = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(10))
            orders = recent_res.scalars().all()
        return [_order_to_response(o) for o in orders]

    stmt = select(Order).where(Order.delivery_boy_id == current_user.id)
    if status_filter:
        stmt = stmt.where(Order.fulfillment_status == status_filter.upper())

    result = await db.execute(stmt.order_by(Order.created_at.desc()))
    orders = result.scalars().all()
    return [_order_to_response(o) for o in orders]


@router.post(
    "/orders/{order_id}/accept",
    summary="Accept an assigned delivery order",
)
async def accept_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(Order.id == order_id)
    else:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.delivery_boy_id == current_user.id,
        )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not assigned to your account.")

    if order.fulfillment_status not in ("ASSIGNED",) and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be accepted from its current state: {order.fulfillment_status}",
        )

    order.fulfillment_status = "ACCEPTED"
    order.delivery_boy_id = order.delivery_boy_id or current_user.id
    order.delivery_accepted_at = datetime.now(timezone.utc)
    order.delivery_rejected_at = None
    order.delivery_rejection_reason = None

    await db.commit()
    await db.refresh(order)
    return _order_to_response(order)


@router.post(
    "/orders/batch-accept",
    summary="Accept all or selected assigned orders in batch",
)
async def batch_accept_orders(
    payload: Optional[BatchAcceptPayload] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    stmt = select(Order).where(Order.fulfillment_status == "ASSIGNED")
    if current_user.role not in ("admin", "superadmin"):
        stmt = stmt.where(Order.delivery_boy_id == current_user.id)

    if payload and payload.order_ids:
        stmt = stmt.where(Order.id.in_(payload.order_ids))

    result = await db.execute(stmt)
    orders = result.scalars().all()

    now = datetime.now(timezone.utc)
    count = 0
    for o in orders:
        o.fulfillment_status = "ACCEPTED"
        o.delivery_boy_id = o.delivery_boy_id or current_user.id
        o.delivery_accepted_at = now
        o.delivery_rejected_at = None
        o.delivery_rejection_reason = None
        count += 1

    await db.commit()
    return {"message": f"{count} orders accepted successfully.", "count": count}


@router.post(
    "/orders/{order_id}/reject",
    summary="Reject an assigned delivery order",
)
async def reject_order(
    order_id: str,
    payload: RejectOrderPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(Order.id == order_id)
    else:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.delivery_boy_id == current_user.id,
        )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not assigned to your account.")

    if order.fulfillment_status not in ("ASSIGNED", "ACCEPTED") and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=400,
            detail=f"Order cannot be rejected from its current state: {order.fulfillment_status}",
        )

    order.fulfillment_status = "REJECTED"
    order.delivery_boy_id = None  # Unassign so admin can reassign
    order.delivery_rejected_at = datetime.now(timezone.utc)
    order.delivery_rejection_reason = payload.reason or "No reason provided"
    order.delivery_accepted_at = None

    await db.commit()
    await db.refresh(order)
    return {"message": "Order rejected. Admin has been notified for reassignment."}


@router.post(
    "/orders/{order_id}/picked",
    summary="Mark order as picked up from store",
)
async def mark_picked_up(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(Order.id == order_id)
    else:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.delivery_boy_id == current_user.id,
        )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not assigned to your account.")

    if order.fulfillment_status not in ("ACCEPTED", "ASSIGNED") and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as picked up from state: {order.fulfillment_status}",
        )

    order.fulfillment_status = "PICKED_UP"
    order.delivery_picked_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(order)
    return _order_to_response(order)


@router.post(
    "/orders/{order_id}/out-for-delivery",
    summary="Mark as Out for Delivery — generates delivery OTP for customer",
)
async def mark_out_for_delivery(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(Order.id == order_id)
    else:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.delivery_boy_id == current_user.id,
        )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not assigned to your account.")

    if order.fulfillment_status not in ("PICKED_UP", "ACCEPTED", "ASSIGNED") and current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark out-for-delivery from state: {order.fulfillment_status}",
        )

    # Generate delivery OTP
    otp = _generate_delivery_otp()
    order.delivery_otp = otp
    order.delivery_otp_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    order.fulfillment_status = "OUT_FOR_DELIVERY"
    order.status = "Out for Delivery"

    await db.commit()
    await db.refresh(order)

    resp = _order_to_response(order)
    return {
        "message": "Order marked as Out for Delivery. Customer OTP has been generated.",
        "order": resp,
        "delivery_otp": otp,  # This OTP is shown in the customer's app
    }


@router.post(
    "/orders/{order_id}/deliver",
    summary="Complete delivery by verifying customer OTP",
)
async def complete_delivery(
    order_id: str,
    payload: VerifyDeliveryOTPPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)

    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(Order.id == order_id)
    else:
        stmt = select(Order).where(
            Order.id == order_id,
            Order.delivery_boy_id == current_user.id,
        )
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found or not assigned to your account.")

    if order.fulfillment_status != "OUT_FOR_DELIVERY":
        if current_user.role in ("admin", "superadmin"):
            # If supervisor is testing, advance to out for delivery automatically
            order.fulfillment_status = "OUT_FOR_DELIVERY"
        else:
            raise HTTPException(
                status_code=400,
                detail="Order must be marked as Out for Delivery before completing delivery.",
            )

    if not order.delivery_otp and current_user.role in ("admin", "superadmin"):
        order.delivery_otp = "123456"
    elif not order.delivery_otp:
        raise HTTPException(status_code=400, detail="Delivery OTP not generated. Please mark order as Out for Delivery first.")

    # OTP verification (constant-time comparison or admin supervisor bypass)
    entered_otp = str(payload.otp).strip()
    is_valid_otp = bool(order.delivery_otp and secrets.compare_digest(entered_otp, str(order.delivery_otp).strip()))
    is_admin_bypass = current_user.role in ("admin", "superadmin") and entered_otp in ("000000", "123456", str(order.delivery_otp or ""))

    if not (is_valid_otp or is_admin_bypass):
        raise HTTPException(status_code=400, detail="Incorrect OTP. Please enter the 6-digit delivery code provided to the customer.")

    # Mark as delivered
    order.fulfillment_status = "DELIVERED"
    order.status = "Delivered"
    order.delivered_at = datetime.now(timezone.utc)
    order.delivery_otp = None  # Clear OTP after use
    order.delivery_otp_expires_at = None

    await db.commit()
    await db.refresh(order)
    return {
        "message": "Order successfully delivered! 🎉",
        "order": _order_to_response(order),
    }


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: DELIVERY BOY MANAGEMENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


@admin_router.get(
    "/delivery-boys",
    response_model=List[DeliveryBoyListItem],
    summary="List all delivery boys with their active order count",
)
async def list_delivery_boys(
    is_active: Optional[bool] = Query(None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.role == "delivery_boy")
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    stmt = stmt.order_by(User.created_at.desc())
    result = await db.execute(stmt)
    boys = result.scalars().all()

    items = []
    for boy in boys:
        # Count active (non-delivered, non-rejected) orders assigned
        active_count = await db.scalar(
            select(func.count(Order.id)).where(
                Order.delivery_boy_id == boy.id,
                Order.fulfillment_status.notin_(["DELIVERED", "REJECTED", "FAILED"]),
            )
        ) or 0
        items.append(
            DeliveryBoyListItem(
                id=boy.id,
                full_name=boy.full_name,
                email=boy.email,
                phone=boy.phone,
                is_active=boy.is_active,
                role=boy.role,
                avatar_url=boy.avatar_url,
                created_at=boy.created_at,
                active_orders=active_count,
            )
        )
    return items


@admin_router.post(
    "/delivery-boys",
    response_model=DeliveryBoyProfileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new delivery boy account",
)
async def create_delivery_boy(
    payload: CreateDeliveryBoyRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.core.security import hash_password

    # Email uniqueness check
    existing = await db.execute(
        select(User).where(func.lower(User.email) == payload.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400,
            detail="A user with this email already exists.",
        )

    new_boy = User(
        full_name=payload.full_name.strip(),
        email=payload.email.lower().strip(),
        phone=payload.phone,
        role="delivery_boy",
        hashed_password=hash_password(payload.password),
        is_active=True,
        is_email_verified=True,
    )
    db.add(new_boy)
    await db.commit()
    await db.refresh(new_boy)

    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="CREATED_DELIVERY_BOY",
        module="delivery",
        description=f"Created delivery boy: {new_boy.full_name} ({new_boy.email})",
    )
    return new_boy


@admin_router.put(
    "/delivery-boys/{delivery_boy_id}",
    response_model=DeliveryBoyProfileResponse,
    summary="Update a delivery boy profile",
)
async def update_delivery_boy(
    delivery_boy_id: str,
    payload: UpdateDeliveryBoyRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.core.security import hash_password

    result = await db.execute(
        select(User).where(User.id == delivery_boy_id, User.role == "delivery_boy")
    )
    boy = result.scalar_one_or_none()
    if not boy:
        raise HTTPException(status_code=404, detail="Delivery boy not found.")

    if payload.full_name is not None and payload.full_name.strip():
        boy.full_name = payload.full_name.strip()
    if payload.email is not None and payload.email.strip().lower() != boy.email:
        existing = await db.execute(
            select(User).where(
                func.lower(User.email) == payload.email.strip().lower(),
                User.id != delivery_boy_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="A user with this email address already exists.")
        boy.email = payload.email.strip().lower()
    if payload.phone is not None:
        boy.phone = payload.phone.strip() if payload.phone.strip() else None
    if payload.password is not None and payload.password.strip():
        if len(payload.password.strip()) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        boy.hashed_password = hash_password(payload.password.strip())
    if payload.is_active is not None:
        boy.is_active = payload.is_active

    await db.commit()
    await db.refresh(boy)

    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="UPDATED_DELIVERY_BOY",
        module="delivery",
        description=f"Updated delivery boy: {boy.full_name} ({boy.email})",
    )
    return boy


@admin_router.delete(
    "/delivery-boys/{delivery_boy_id}",
    summary="Deactivate a delivery boy account",
)
async def deactivate_delivery_boy(
    delivery_boy_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == delivery_boy_id, User.role == "delivery_boy")
    )
    boy = result.scalar_one_or_none()
    if not boy:
        raise HTTPException(status_code=404, detail="Delivery boy not found.")

    boy.is_active = False

    # Unassign all pending orders
    pending_orders_result = await db.execute(
        select(Order).where(
            Order.delivery_boy_id == delivery_boy_id,
            Order.fulfillment_status.in_(["ASSIGNED", "ACCEPTED"]),
        )
    )
    pending_orders = pending_orders_result.scalars().all()
    for o in pending_orders:
        o.delivery_boy_id = None
        o.fulfillment_status = "UNASSIGNED"

    await db.commit()
    return {
        "message": f"Delivery boy '{boy.full_name}' deactivated. "
                   f"{len(pending_orders)} order(s) returned to unassigned queue."
    }


@admin_router.post(
    "/orders/{order_id}/assign-delivery-boy",
    summary="Assign an order to a delivery boy",
)
async def assign_delivery_boy(
    order_id: str,
    payload: AssignDeliveryBoyPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # Validate order
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # Validate delivery boy
    boy_result = await db.execute(
        select(User).where(
            User.id == payload.delivery_boy_id,
            User.role == "delivery_boy",
            User.is_active == True,
        )
    )
    boy = boy_result.scalar_one_or_none()
    if not boy:
        raise HTTPException(
            status_code=404,
            detail="Active delivery boy not found.",
        )

    order.delivery_boy_id = boy.id
    order.fulfillment_type = "LOCAL"
    order.fulfillment_status = "ASSIGNED"
    order.delivery_accepted_at = None
    order.delivery_rejected_at = None
    order.delivery_rejection_reason = None

    await db.commit()
    await db.refresh(order)

    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="ASSIGNED_DELIVERY_BOY",
        module="delivery",
        description=f"Assigned order {order.id} to delivery boy {boy.full_name} ({boy.email})",
    )
    return _order_to_response(order)


@admin_router.post(
    "/orders/{order_id}/unassign-delivery-boy",
    summary="Unassign a delivery boy from an order",
)
async def unassign_delivery_boy(
    order_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if order.fulfillment_status in ("DELIVERED", "OUT_FOR_DELIVERY"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot unassign from a {order.fulfillment_status} order.",
        )

    order.delivery_boy_id = None
    order.fulfillment_status = "UNASSIGNED"
    order.delivery_accepted_at = None
    order.delivery_rejected_at = None
    order.delivery_rejection_reason = None
    order.delivery_otp = None
    order.delivery_otp_expires_at = None

    await db.commit()
    await db.refresh(order)
    return {"message": "Delivery boy unassigned. Order returned to queue."}


@admin_router.get(
    "/orders/{order_id}/delivery-otp",
    summary="[Admin] View current delivery OTP for an order (for support/debugging)",
)
async def get_order_delivery_otp(
    order_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    order_result = await db.execute(select(Order).where(Order.id == order_id))
    order = order_result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    if not order.delivery_otp:
        return {"otp": None, "message": "No active delivery OTP for this order."}

    return {
        "otp": order.delivery_otp,
        "expires_at": order.delivery_otp_expires_at,
        "order_id": order.id,
        "fulfillment_status": order.fulfillment_status,
    }


# ══════════════════════════════════════════════════════════════════════════════
# DELIVERY BOY LOCATION ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════


class LocationUpdatePayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: Optional[float] = None  # metres


class RouteStop(BaseModel):
    stop_number: int
    order_id: str
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None
    fulfillment_status: str
    total: float
    items_count: int
    google_maps_url: str


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometres using the Haversine formula."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


@router.post(
    "/location",
    summary="Update delivery person's current GPS location",
)
async def update_location(
    payload: LocationUpdatePayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upsert the delivery person's latest location.
    Uses delivery_person_id as the primary key, so only one row per person
    is kept — no unbounded history table growth.
    The backend derives the delivery person ID from the access token;
    the client never supplies it.
    """
    _require_delivery_boy(current_user)

    # Validate coordinates
    if not (-90 <= payload.latitude <= 90) or not (-180 <= payload.longitude <= 180):
        raise HTTPException(status_code=400, detail="Invalid GPS coordinates.")

    result = await db.execute(
        select(DeliveryPersonLocation).where(
            DeliveryPersonLocation.delivery_person_id == current_user.id
        )
    )
    loc = result.scalar_one_or_none()

    if loc:
        loc.latitude = payload.latitude
        loc.longitude = payload.longitude
        loc.accuracy = payload.accuracy
        # updated_at auto-updates via onupdate
    else:
        loc = DeliveryPersonLocation(
            delivery_person_id=current_user.id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
        )
        db.add(loc)

    await db.commit()
    return {"message": "Location updated.", "updated_at": loc.updated_at}


@router.get(
    "/location",
    summary="Get this delivery person's last known location",
)
async def get_my_location(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_delivery_boy(current_user)
    result = await db.execute(
        select(DeliveryPersonLocation).where(
            DeliveryPersonLocation.delivery_person_id == current_user.id
        )
    )
    loc = result.scalar_one_or_none()
    if not loc:
        return {"latitude": None, "longitude": None, "accuracy": None, "updated_at": None}
    return {
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "accuracy": loc.accuracy,
        "updated_at": loc.updated_at,
    }


@router.get(
    "/route",
    summary="Get optimised multi-stop delivery route for accepted orders",
)
async def get_delivery_route(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns accepted orders sorted by nearest-neighbour geographic distance
    from the delivery person's current location.
    Falls back gracefully when no location is available.
    """
    _require_delivery_boy(current_user)

    # 1. Get current location
    loc_result = await db.execute(
        select(DeliveryPersonLocation).where(
            DeliveryPersonLocation.delivery_person_id == current_user.id
        )
    )
    current_loc = loc_result.scalar_one_or_none()

    # 2. Fetch accepted/in-progress orders
    if current_user.role in ("admin", "superadmin"):
        stmt = select(Order).where(
            Order.fulfillment_status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"])
        )
    else:
        stmt = select(Order).where(
            Order.delivery_boy_id == current_user.id,
            Order.fulfillment_status.in_(["ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY"]),
        )

    result = await db.execute(stmt)
    orders = result.scalars().all()

    if not orders:
        return {"stops": [], "current_location": None, "message": "No active deliveries."}

    # 3. Nearest-neighbour sort (Haversine)
    current_lat = current_loc.latitude if current_loc else None
    current_lng = current_loc.longitude if current_loc else None

    def _build_stop(order: Order, stop_num: int, dist_km: Optional[float]) -> dict:
        lat = order.shipping_latitude
        lng = order.shipping_longitude
        addr = (
            order.shipping_formatted_address
            or ", ".join(filter(None, [
                order.shipping_house_number,
                order.shipping_street,
                order.shipping_area,
                order.shipping_city,
                order.shipping_state,
                order.shipping_pincode,
            ]))
        )
        maps_url = (
            f"https://www.google.com/maps/dir/?api=1&destination={lat},{lng}"
            if lat and lng
            else f"https://www.google.com/maps/search/?api=1&query={addr}"
        )
        customer_name = (
            (order.user.full_name if order.user else None)
            or order.shipping_name
        )
        customer_phone = (
            (order.user.phone if order.user else None)
            or order.shipping_phone
        )
        return {
            "stop_number": stop_num,
            "order_id": order.id,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "address": addr,
            "latitude": lat,
            "longitude": lng,
            "distance_km": round(dist_km, 2) if dist_km is not None else None,
            "fulfillment_status": order.fulfillment_status,
            "total": order.total,
            "items_count": len(order.items or []),
            "google_maps_url": maps_url,
        }

    if current_lat is not None and current_lng is not None:
        # Nearest-neighbour greedy sort
        remaining = list(orders)
        sorted_stops: list = []
        from_lat, from_lng = current_lat, current_lng

        while remaining:
            best_idx = 0
            best_dist = float("inf")
            for i, o in enumerate(remaining):
                if o.shipping_latitude and o.shipping_longitude:
                    d = _haversine_km(from_lat, from_lng, o.shipping_latitude, o.shipping_longitude)
                else:
                    d = float("inf")  # no coords → push to end
                if d < best_dist:
                    best_dist = d
                    best_idx = i
            chosen = remaining.pop(best_idx)
            sorted_stops.append((chosen, best_dist if best_dist != float("inf") else None))
            if chosen.shipping_latitude and chosen.shipping_longitude:
                from_lat, from_lng = chosen.shipping_latitude, chosen.shipping_longitude

        stops = [
            _build_stop(o, idx + 1, dist)
            for idx, (o, dist) in enumerate(sorted_stops)
        ]
    else:
        # No location — return orders in created_at order without distances
        stops = [
            _build_stop(o, idx + 1, None)
            for idx, o in enumerate(orders)
        ]

    return {
        "stops": stops,
        "current_location": {
            "latitude": current_lat,
            "longitude": current_lng,
        } if current_lat else None,
        "total_stops": len(stops),
    }
