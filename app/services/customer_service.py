import logging
import os
import re
import urllib.parse
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.storage import storage_service
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.repositories.contact_repository import ContactRepository
from app.repositories.coupon_repository import CouponRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.reel_repository import ReelRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.ticket_repository import TicketRepository
from app.repositories.user_repository import UserRepository
from app.repositories.site_config_repository import SiteConfigRepository
from app.core.config import settings
from app.services.mail_service import MailService

from app.schemas.contact import ContactMessageRequest, ContactMessageResponse
from app.schemas.coupon import CouponValidationRequest, CouponValidationResponse, UserCouponResponse
from app.schemas.order import OrderPayload, OrderResponse, CartItemResponse, ShippingAddressSchema, OrderItemResponse
from app.schemas.product import ProductResponse, ReviewResponse
from app.schemas.ticket import CreateTicketPayload, SupportTicketResponse, TicketFeedbackPayload
from app.schemas.user import (
    AddressSchema,
    AvatarUploadResponse,
    CustomerAddressCreate,
    CustomerAddressResponse,
    CustomerAddressUpdate,
    ProfileUpdatePayload,
    SupportNotificationResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)


def _format_order_items_html(order) -> str:
    items_html = ""
    for item in getattr(order, "items", []) or []:
        p_name = "Chovique Product"
        if getattr(item, "product", None) and getattr(item.product, "name", None):
            p_name = item.product.name
        elif getattr(item, "product_name", None):
            p_name = item.product_name
        qty = getattr(item, "quantity", 1) or 1
        price = float(getattr(item, "price", 0.0) or 0.0)
        items_html += f"<li>{p_name} x {qty} (₹{price * qty:,.2f})</li>"
    return items_html


class CustomerService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(db)
        self.address_repo = AddressRepository(db)
        self.coupon_repo = CouponRepository(db)
        self.order_repo = OrderRepository(db)
        self.ticket_repo = TicketRepository(db)
        self.notification_repo = NotificationRepository(db)
        self.contact_repo = ContactRepository(db)
        self.review_repo = ReviewRepository(db)
        self.product_repo = ProductRepository(db)
        self.reel_repo = ReelRepository(db)
        self.config_repo = SiteConfigRepository(db)

    # ==========================================================
    # Profile & Avatar
    # ==========================================================

    async def update_profile(
        self,
        user_id: str,
        payload: ProfileUpdatePayload,
    ) -> UserResponse:

        update_dict = {}
        if payload.full_name is not None:
            update_dict["full_name"] = payload.full_name
        elif payload.name is not None:
            update_dict["full_name"] = payload.name

        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise ValueError("User not found.")

        if payload.phone is not None:
            update_dict["phone"] = payload.phone
        if payload.gender is not None:
            update_dict["gender"] = payload.gender
        if payload.dob is not None:
            try:
                update_dict["dob"] = datetime.strptime(payload.dob, "%Y-%m-%d").date()
            except Exception:
                pass

        has_address_update = any(
            x is not None for x in [
                payload.address_street,
                payload.address_city,
                payload.address_state,
                payload.address_zip
            ]
        )
        address_repo = AddressRepository(self.db)
        if has_address_update:
            addresses = await address_repo.get_user_addresses(user_id)
            default_addr = next((a for a in addresses if a.is_default), addresses[0] if addresses else None)
            if default_addr:
                if payload.address_street is not None:
                    default_addr.street = payload.address_street
                if payload.address_city is not None:
                    default_addr.city = payload.address_city
                if payload.address_state is not None:
                    default_addr.state = payload.address_state
                if payload.address_zip is not None:
                    default_addr.zip = payload.address_zip
                await self.db.commit()
            else:
                await address_repo.create(
                    user_id=user_id,
                    title="Home",
                    name=update_dict.get("full_name") or user.full_name or "Customer",
                    phone=payload.phone or user.phone or "",
                    street=payload.address_street or "",
                    city=payload.address_city or "",
                    state=payload.address_state or "",
                    zip=payload.address_zip or "",
                    is_default=True,
                )

        user = await self.user_repo.update_profile(user_id, **update_dict)
        res = UserResponse.from_orm_user(user)
        addresses = await address_repo.get_user_addresses(user_id)
        default_addr = next((a for a in addresses if a.is_default), None)
        if default_addr:
            res.profile.address = AddressSchema(
                street=default_addr.street,
                city=default_addr.city,
                state=default_addr.state,
                zip=default_addr.zip,
            )
        return res

    async def upload_avatar(
        self,
        user_id: str,
        file: UploadFile,
    ) -> AvatarUploadResponse:
        user = await self.user_repo.get_by_id(user_id)
        if user and user.avatar_url:
            old_public_id = storage_service.extract_public_id(user.avatar_url)
            if old_public_id:
                try:
                    storage_service.delete_media(old_public_id)
                except Exception as e:
                    logger.warning("Failed to delete previous S3 avatar '%s' for user %s: %s", old_public_id, user_id, e)

        if not file.filename:
            file.filename = f"{user_id}.jpg"

        avatar_url = await storage_service.upload_image(
            file=file,
            folder="chocolate-world/avatars",
        )

        await self.user_repo.update_profile(user_id, avatar_url=avatar_url)

        return AvatarUploadResponse(avatar_url=avatar_url)

    # ==========================================================
    # Addresses
    # ==========================================================

    async def get_addresses(self, user_id: str) -> list[CustomerAddressResponse]:
        addresses = await self.address_repo.get_user_addresses(user_id)
        return [
            CustomerAddressResponse(
                id=a.id,
                title=a.title,
                name=a.name,
                street=a.street,
                city=a.city,
                state=a.state,
                zip=a.zip,
                phone=a.phone,
                isDefault=a.is_default,
            )
            for a in addresses
        ]

    async def add_address(
        self,
        user_id: str,
        payload: CustomerAddressCreate,
    ) -> CustomerAddressResponse:

        addr = await self.address_repo.create(
            user_id=user_id,
            title=payload.title,
            name=payload.name,
            street=payload.street,
            city=payload.city,
            state=payload.state,
            zip=payload.zip,
            phone=payload.phone,
            is_default=payload.isDefault,
        )

        return CustomerAddressResponse(
            id=addr.id,
            title=addr.title,
            name=addr.name,
            street=addr.street,
            city=addr.city,
            state=addr.state,
            zip=addr.zip,
            phone=addr.phone,
            isDefault=addr.is_default,
        )

    async def update_address(
        self,
        user_id: str,
        address_id: str,
        payload: CustomerAddressUpdate,
    ) -> CustomerAddressResponse | None:
        update_data = payload.model_dump(exclude_unset=True)
        if "isDefault" in update_data:
            update_data["is_default"] = update_data.pop("isDefault")

        addr = await self.address_repo.update(address_id, user_id, **update_data)
        if not addr:
            return None

        return CustomerAddressResponse(
            id=addr.id,
            title=addr.title,
            name=addr.name,
            street=addr.street,
            city=addr.city,
            state=addr.state,
            zip=addr.zip,
            phone=addr.phone,
            isDefault=addr.is_default,
        )

    async def delete_address(self, user_id: str, address_id: str) -> bool:
        return await self.address_repo.delete(address_id, user_id)

    async def set_default_address(
        self,
        user_id: str,
        address_id: str,
    ) -> CustomerAddressResponse | None:

        addr = await self.address_repo.set_default(address_id, user_id)
        if not addr:
            return None

        return CustomerAddressResponse(
            id=addr.id,
            title=addr.title,
            name=addr.name,
            street=addr.street,
            city=addr.city,
            state=addr.state,
            zip=addr.zip,
            phone=addr.phone,
            isDefault=addr.is_default,
        )

    # ==========================================================
    # Coupons
    # ==========================================================



    # ==========================================================
    # Orders
    # ==========================================================

    async def place_order(
        self,
        user_id: str,
        payload: OrderPayload,
    ) -> OrderResponse:

        try:
            # Validate Shipping Address
            addr = payload.shipping_address
            name_clean = (addr.name or "").strip()
            street_clean = (addr.street or "").strip()
            city_clean = (addr.city or "").strip()
            state_clean = (addr.state or "").strip()
            zip_clean = (addr.zip or "").strip()
            phone_clean = (addr.phone or "").strip()

            if not name_clean:
                raise ValueError("Full name is required.")
            if not street_clean:
                raise ValueError("Street address is required.")
            if not city_clean:
                raise ValueError("City is required.")
            if not state_clean:
                raise ValueError("State is required.")
            if not zip_clean or not zip_clean.isdigit() or len(zip_clean) != 6:
                raise ValueError("ZIP/PIN code must contain exactly 6 numeric digits.")
            phone_digits = "".join(c for c in phone_clean if c.isdigit())
            if len(phone_digits) == 12 and phone_digits.startswith("91"):
                phone_digits = phone_digits[2:]
            if len(phone_digits) != 10:
                raise ValueError("Phone number must contain exactly 10 numeric digits.")

            # Validate Guest Checkout, COD, and Minimum Order Value via PlatformSettings
            from app.repositories.platform_settings_repository import PlatformSettingsRepository
            ps_repo = PlatformSettingsRepository(self.db)
            ps = await ps_repo.get()

            user_obj = await self.user_repo.get_by_id(user_id)
            if user_obj and getattr(user_obj, "is_guest", False) and not ps.guest_checkout_enabled:
                raise ValueError("Guest checkout is currently disabled by system configuration.")

            # Validate Payment Method
            valid_methods = ["Credit Card", "UPI / Google Pay", "UPI", "Google Pay", "Net Banking", "Cash on Delivery", "COD", "Cash On Delivery"]
            if not payload.payment_method or payload.payment_method not in valid_methods:
                raise ValueError("Please select a valid payment option.")

            is_cod = payload.payment_method in ("Cash on Delivery", "COD", "Cash On Delivery")
            if is_cod and not ps.cod_enabled:
                raise ValueError("Cash on Delivery (COD) is currently disabled by system configuration.")

            subtotal = 0.0
            items_data = []

            # If payload items are empty, use user's persistent cart items
            items_to_process = payload.items
            if not items_to_process:
                from app.repositories.cart_repository import CartRepository
                cart_repo = CartRepository(self.db)
                user_cart = await cart_repo.get_or_create_user_cart(user_id, commit=False)
                items_to_process = [
                    type("CartItemPayload", (), {"product_id": ci.product_id, "quantity": ci.quantity})()
                    for ci in user_cart.items
                ]

            if not items_to_process:
                raise ValueError("Cannot place order with an empty cart.")

            for item in items_to_process:
                product = await self.product_repo.get_by_id(item.product_id)
                if not product or not product.is_active or getattr(product, "is_available", True) is False:
                    pname = product.name if product else item.product_id
                    raise ValueError(f"Product '{pname}' is currently unavailable for purchase.")

                if product.stock <= 0:
                    raise ValueError(f"Product '{product.name}' is out of stock.")

                if product.stock < item.quantity:
                    raise ValueError(f"Insufficient stock for '{product.name}'. Only {product.stock} units available.")

                item_price = product.price
                subtotal += item_price * item.quantity
                items_data.append({
                    "product_id": product.id,
                    "quantity": item.quantity,
                    "price": item_price,
                })

            # Coupon validation
            coupon_discount = 0.0
            if payload.coupon_code:
                from app.services.coupon_service import CouponService
                c_service = CouponService(self.db)
                val_res = await c_service.validate_and_calculate_discount(
                    user_id=user_id,
                    code=payload.coupon_code,
                    items=items_data,
                    subtotal=subtotal,
                )
                if not val_res.valid:
                    raise ValueError(val_res.message or "Invalid, expired, or already used coupon code.")
                coupon_discount = val_res.calculated_discount

            # Coin redemption validation
            coins_used = 0
            coin_discount = 0.0
            from app.services.wallet_service import WalletService
            wallet_service = WalletService(self.db)

            if payload.coins_to_use and payload.coins_to_use > 0:
                redemption_calc = await wallet_service.calculate_redemption(
                    user_id=user_id,
                    subtotal=subtotal,
                    coupon_discount=coupon_discount,
                    coins_requested=payload.coins_to_use,
                )
                if redemption_calc.user_balance < payload.coins_to_use:
                    raise ValueError(f"Insufficient coin balance. Available balance: {redemption_calc.user_balance} coins.")
                if redemption_calc.allowed_coins <= 0:
                    raise ValueError(redemption_calc.message or "Reward coins cannot be applied to this order.")
                coins_used = redemption_calc.allowed_coins
                coin_discount = redemption_calc.coin_discount

            if ps.minimum_order_value > 0 and subtotal < ps.minimum_order_value:
                raise ValueError(f"Minimum order value required is ₹{ps.minimum_order_value:.2f}.")

            if is_cod and ps.maximum_cod_order_value > 0 and subtotal > ps.maximum_cod_order_value:
                raise ValueError(f"Cash on Delivery is not available for order subtotal exceeding ₹{ps.maximum_cod_order_value:.2f}.")

            total_discount = coupon_discount + coin_discount
            if ps.free_shipping_min_order > 0 and subtotal >= ps.free_shipping_min_order:
                shipping = 0.0
            else:
                shipping = ps.standard_shipping_charge

            tax = round(subtotal * (ps.gst_rate / 100.0), 2)
            total = max(0.0, subtotal - total_discount + shipping + tax)
            total = round(total, 2)

            shipping_addr_dict = payload.shipping_address.model_dump()

            # Determine payment_status based on payment method
            # Direct order creation (e.g. COD): payment not yet collected -> PENDING
            is_cod = payload.payment_method in ("Cash on Delivery", "COD", "Cash On Delivery")
            if not is_cod:
                logger.info("Direct order creation called for non-COD payment method %s. Setting payment_status=PENDING until verified.", payload.payment_method)
            initial_payment_status = "PENDING"

            order = await self.order_repo.create_order(
                user_id=user_id,
                total=total,
                subtotal=round(subtotal, 2),
                discount=round(total_discount, 2),
                coupon_code=payload.coupon_code if coupon_discount > 0 else None,
                coupon_discount=round(coupon_discount, 2),
                coins_used=coins_used,
                coin_discount=round(coin_discount, 2),
                coins_earned=0,  # Will be calculated and set below
                shipping=round(shipping, 2),
                tax=round(tax, 2),
                shipping_address=shipping_addr_dict,
                delivery_option=payload.delivery_option,
                payment_method=payload.payment_method,
                payment_status=initial_payment_status,
                items_data=items_data,
                commit=False,
            )

            # Deduct redeemed coins from wallet
            if coins_used > 0:
                await wallet_service.redeem_coins(
                    user_id=user_id,
                    order_id=order.id,
                    coins=coins_used,
                    commit=False,
                )

            # Calculate and credit earned coins for confirmed order
            coins_earned, _ = await wallet_service.earn_coins(
                user_id=user_id,
                order_id=order.id,
                payable_amount=total,
                commit=False,
            )
            order.coins_earned = coins_earned

            if payload.coupon_code and coupon_discount > 0:
                from app.models.coupon import CouponUsage
                from sqlalchemy import select, func
                coupon = await self.coupon_repo.get_by_code(payload.coupon_code)
                if coupon:
                    existing_usage_q = select(func.count(CouponUsage.id)).where(
                        CouponUsage.coupon_id == coupon.id,
                        CouponUsage.order_id == order.id
                    )
                    already_recorded = (await self.db.execute(existing_usage_q)).scalar() or 0
                    if already_recorded == 0:
                        self.db.add(CouponUsage(
                            coupon_id=coupon.id,
                            user_id=user_id,
                            order_id=order.id,
                            discount_amount=coupon_discount or 0.0
                        ))

            # Clean up ordered items from database Cart & Wishlist tables
            from app.repositories.cart_repository import CartRepository
            from app.repositories.wishlist_repository import WishlistRepository

            cart_repo = CartRepository(self.db)
            wishlist_repo = WishlistRepository(self.db)
            user_cart = await cart_repo.get_or_create_user_cart(user_id, commit=False)

            for item_data in items_data:
                pid = item_data["product_id"]
                await cart_repo.remove_item(user_cart.id, pid, commit=False)
                await wishlist_repo.remove_item(user_id, pid, commit=False)
                
                # Deduct stock immediately
                product = await self.product_repo.get_by_id(pid)
                if product:
                    if product.stock < item_data["quantity"]:
                        raise ValueError(f"Insufficient stock for '{product.name}'. Only {product.stock} units available.")
                    new_stock = product.stock - item_data["quantity"]
                    await self.product_repo.update(product.id, stock=new_stock, commit=False)
                    if new_stock <= 10:
                        try:
                            from app.services.notification_service import NotificationService
                            notif_svc = NotificationService(self.db)
                            await notif_svc.notify_low_stock(product.id, product.name, new_stock, commit=False)
                        except Exception as exc:
                            logger.error("Failed to send low stock notification on checkout: %s", exc)

            # Atomic commit of all staging changes
            await self.db.commit()

        except Exception as exc:
            await self.db.rollback()
            raise exc

        # Send Email Confirmation immediately after transaction commits
        try:
            from app.integrations.resend import resend_email
            import asyncio
            user = await self.user_repo.get_by_id(user_id)
            if user and user.email:
                items_html = ""
                try:
                    for it_data in items_data:
                        prod = await self.product_repo.get_by_id(it_data.get("product_id"))
                        p_name = prod.name if prod else "Artisanal Chocolate"
                        qty = it_data.get("quantity", 1)
                        prc = it_data.get("price", 0.0)
                        items_html += f"<li><strong>{p_name}</strong> × {qty} — ₹{prc * qty:,.2f}</li>"
                except Exception:
                    pass

                asyncio.create_task(
                    resend_email.send_order_confirmation(
                        email=user.email,
                        name=user.full_name or "Valued Customer",
                        order_id=order.id,
                        total=order.total,
                        payment_status=order.payment_status,
                        payment_method=order.payment_method or "Cash on Delivery (COD)",
                        items_html=items_html,
                        delivery_option=order.delivery_option or "Standard Delivery",
                    )
                )
        except Exception as e:
            logger.error(f"Failed to trigger email for order {order.id}: {e}")

        # Generate & Upload Invoice to S3 storage
        try:
            from app.services.invoice_service import InvoiceService
            user = await self.user_repo.get_by_id(user_id)
            user_name = user.full_name if user else "Customer"
            user_email = user.email if user else ""
            db_order = await self.order_repo.get_by_id(order.id)
            if db_order:
                inv_url = await InvoiceService.generate_and_upload_invoice(db_order, user_name, user_email)
                if inv_url:
                    db_order.invoice_url = inv_url
                    await self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to process S3 invoice for order {order.id}: {e}")

        try:
            db_order = await self.order_repo.get_by_id(order.id)
            return self._format_order_response(db_order or order)
        except Exception as e:
            logger.error(f"Failed to format order response for order {order.id}: {e}")
            return self._format_order_response(order)

    async def get_user_orders(self, user_id: str, role: str = "customer") -> list[OrderResponse]:
        if role in ["admin", "superadmin"]:
            personal_orders = await self.order_repo.get_user_orders(user_id)
            if personal_orders:
                orders = personal_orders
            else:
                orders = await self.order_repo.get_all_orders_for_admin()
        else:
            orders = await self.order_repo.get_user_orders(user_id)
        return [self._format_order_response(o) for o in orders]

    async def get_order_by_id(self, order_id: str, user_id: str) -> OrderResponse | None:
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.user_id != user_id:
            return None
        return self._format_order_response(order)

    async def cancel_order(self, order_id: str, user_id: str, reason: str | None = None) -> OrderResponse | None:
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.user_id != user_id:
            return None

        from app.repositories.platform_settings_repository import PlatformSettingsRepository
        ps_repo = PlatformSettingsRepository(self.db)
        ps = await ps_repo.get()

        if not ps.order_cancellation_enabled:
            raise ValueError("Order cancellation is currently disabled by system configuration.")

        if order.status in ("Shipped", "Out for Delivery", "Out_For_Delivery", "Delivered", "Cancelled", "Returned", "Refunded"):
            raise ValueError("Order cannot be cancelled because it is already shipped, delivered, or cancelled.")

        if order.status not in ("Pending", "Confirmed", "Processing"):
            raise ValueError("Order cannot be cancelled in its current state.")

        if order.created_at:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            created_at = order.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            diff_hours = (now - created_at).total_seconds() / 3600.0
            limit = ps.cancellation_time_limit if (ps and ps.cancellation_time_limit) else 24
            if diff_hours >= limit:
                raise ValueError(f"Order cancellation time limit ({limit} hours from placement) has passed.")

        order.status = "Cancelled"
        if hasattr(order, "cancelled_at"):
            from datetime import datetime, timezone
            order.cancelled_at = datetime.now(timezone.utc)
        if hasattr(order, "cancellation_reason") and reason:
            order.cancellation_reason = reason

        current_ps = (order.payment_status or "Pending").strip()
        if current_ps.upper() == "PAID":
            order.payment_status = "Refund Pending"
        elif current_ps.upper() in ("PENDING", "PROCESSING"):
            order.payment_status = "Cancelled"

        # Refund coins used and reverse coins earned
        from app.services.wallet_service import WalletService
        wallet_service = WalletService(self.db)
        await wallet_service.refund_order_coins(
            user_id=user_id,
            order_id=order.id,
            coins_used=order.coins_used or 0,
            coins_earned=order.coins_earned or 0,
            commit=False,
        )

        for item in order.items:
            if item.product:
                await self.product_repo.update(
                    item.product_id,
                    stock=item.product.stock + item.quantity,
                    commit=False
                )
        
        self.db.add(order)
        await self.db.commit()

        # Trigger customer email notification on cancellation (non-blocking)
        try:
            user = await self.user_repo.get_by_id(user_id)
            if user and user.email:
                import asyncio
                from app.integrations.resend import resend_email
                created_str = order.created_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(order, "created_at", None) else ""
                cancelled_str = order.cancelled_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(order, "cancelled_at", None) else ""
                items_html = _format_order_items_html(order)
                asyncio.create_task(
                    resend_email.send_cancellation(
                        email=user.email,
                        name=user.full_name or "Valued Customer",
                        order_id=order.id,
                        cancellation_reason=getattr(order, "cancellation_reason", None) or reason or "Customer Request",
                        order_total=float(order.total or 0.0),
                        order_date=created_str,
                        cancelled_at=cancelled_str,
                        payment_method=str(order.payment_method or "UPI"),
                        payment_status=str(getattr(order, "payment_status", "Cancelled") or "Cancelled"),
                        order_items_html=items_html,
                    )
                )
        except Exception as e_mail:
            logger.warning("Order email notification dispatch failed | Event: ORDER_CANCELLED | Order: %s | Reason: %s", order.id, e_mail)

        return self._format_order_response(order)

    async def return_order(self, order_id: str, user_id: str, reason: str | None = None) -> OrderResponse | None:
        order = await self.order_repo.get_by_id(order_id)
        if not order or order.user_id != user_id:
            return None

        if order.status != "Delivered":
            raise ValueError("Only delivered orders can be requested for return.")

        if (order.payment_status or "").upper() in ("REFUNDED", "PARTIALLY REFUNDED") or order.status in ("Returned", "Return Requested"):
            raise ValueError("This order has already been returned or refunded.")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        delivery_dt = getattr(order, "delivered_at", None)
        if not delivery_dt:
            raise ValueError("A valid delivery timestamp is required to request a return.")
        if delivery_dt.tzinfo is None:
            delivery_dt = delivery_dt.replace(tzinfo=timezone.utc)
        diff_days = (now - delivery_dt).total_seconds() / 86400.0
        if diff_days >= 4.0:
            raise ValueError("The 4-day return window after delivery has expired.")

        order.status = "Return Requested"
        if hasattr(order, "returned_at"):
            order.returned_at = now
        if hasattr(order, "return_reason") and reason:
            order.return_reason = reason

        self.db.add(order)
        await self.db.commit()

        try:
            from app.repositories.notification_repository import NotificationRepository
            notif_repo = NotificationRepository(self.db)
            await notif_repo.create(
                user_id=order.user_id,
                title="Return Requested",
                message=f"Return request submitted for Order #{order.id}.",
                type="order",
                link=f"/dashboard?tab=orders&order_id={order.id}"
            )
        except Exception as e:
            logger.warning(f"Failed to create return notification: {e}")

        # Trigger customer email notification on return request (non-blocking)
        try:
            user = await self.user_repo.get_by_id(user_id)
            if user and user.email:
                import asyncio
                from app.integrations.resend import resend_email
                returned_str = order.returned_at.strftime("%Y-%m-%d %H:%M:%S") if getattr(order, "returned_at", None) else ""
                items_html = _format_order_items_html(order)
                asyncio.create_task(
                    resend_email.send_return_request(
                        email=user.email,
                        name=user.full_name or "Valued Customer",
                        order_id=order.id,
                        return_requested_at=returned_str,
                        return_reason=getattr(order, "return_reason", None) or reason or "Customer Request",
                        return_items_html=items_html,
                    )
                )
        except Exception as e_mail:
            logger.warning("Order email notification dispatch failed | Event: RETURN_REQUESTED | Order: %s | Reason: %s", order.id, e_mail)

        db_order = await self.order_repo.get_by_id(order.id)
        return self._format_order_response(db_order or order)

    def _format_order_response(self, order) -> OrderResponse:
        cart_items = []
        for item in getattr(order, "items", []) or []:
            if getattr(item, "product", None):
                try:
                    product_res = ProductResponse.from_orm_model(item.product)
                except Exception:
                    product_res = ProductResponse(
                        id=str(getattr(item.product, "id", "") or item.product_id or "unknown"),
                        name=getattr(item.product, "name", "Chovique Product") or "Chovique Product",
                        slug=getattr(item.product, "slug", "product") or "product",
                        category=getattr(item.product, "category", "Chocolates") or "Chocolates",
                        price=float(getattr(item.product, "price", item.price or 0.0) or 0.0),
                    )
            else:
                product_res = ProductResponse(
                    id=str(item.product_id or "unknown"),
                    name="Chovique Product",
                    slug="product",
                    category="Chocolates",
                    price=float(item.price or 0.0),
                )
            cart_items.append(OrderItemResponse(product=product_res, quantity=item.quantity or 1, price=float(item.price or 0.0)))

        ship_addr_raw = getattr(order, "shipping_address", None)
        if isinstance(ship_addr_raw, dict):
            ship_addr = ShippingAddressSchema(
                name=str(ship_addr_raw.get("name") or ""),
                street=str(ship_addr_raw.get("street") or ""),
                city=str(ship_addr_raw.get("city") or ""),
                state=str(ship_addr_raw.get("state") or ""),
                zip=str(ship_addr_raw.get("zip") or ship_addr_raw.get("zip_code") or ""),
                phone=str(ship_addr_raw.get("phone") or ""),
            )
        elif hasattr(ship_addr_raw, "name"):
            ship_addr = ShippingAddressSchema(
                name=str(getattr(ship_addr_raw, "name", "") or ""),
                street=str(getattr(ship_addr_raw, "street", "") or ""),
                city=str(getattr(ship_addr_raw, "city", "") or ""),
                state=str(getattr(ship_addr_raw, "state", "") or ""),
                zip=str(getattr(ship_addr_raw, "zip", "") or ""),
                phone=str(getattr(ship_addr_raw, "phone", "") or ""),
            )
        else:
            ship_addr = ShippingAddressSchema(name="", street="", city="", state="", zip="", phone="")

        created_date = order.created_at.strftime("%Y-%m-%d") if getattr(order, "created_at", None) else datetime.now().strftime("%Y-%m-%d")

        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)

        # 1. Cancel Order eligibility: within 24 hours from creation AND status in (Pending, Confirmed, Processing)
        is_cancellable = False
        if str(order.status or "") in ("Pending", "Confirmed", "Processing"):
            created_dt = getattr(order, "created_at", None)
            if created_dt:
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                diff_hours = (now_utc - created_dt).total_seconds() / 3600.0
                if diff_hours < 24.0:
                    is_cancellable = True

        # 2. Return Order eligibility: status is Delivered, valid delivery timestamp exists, within 4 days from delivery, not returned/refunded
        is_returnable = False
        if str(order.status or "") == "Delivered" and str(getattr(order, "payment_status", "") or "").upper() not in ("REFUNDED", "PARTIALLY REFUNDED") and str(order.status or "") not in ("Returned", "Return Requested"):
            delivery_dt = getattr(order, "delivered_at", None)
            if delivery_dt:
                if delivery_dt.tzinfo is None:
                    delivery_dt = delivery_dt.replace(tzinfo=timezone.utc)
                diff_days = (now_utc - delivery_dt).total_seconds() / 86400.0
                if diff_days < 4.0:
                    is_returnable = True

        # Generate WhatsApp order confirmation links
        cust_phone_clean = re.sub(r"\D", "", str(ship_addr.phone or "")) if ship_addr else ""
        if cust_phone_clean and len(cust_phone_clean) == 10:
            cust_phone_clean = "91" + cust_phone_clean

        owner_whatsapp = "+91 83098 54870"
        owner_phone_clean = re.sub(r"\D", "", str(owner_whatsapp))

        items_summary = []
        for it in cart_items:
            pname = it.product.name if hasattr(it.product, "name") else "Chocolate"
            items_summary.append(f"• {pname} × {it.quantity} (₹{it.price * it.quantity:,.2f})")
        items_str = "\n".join(items_summary) if items_summary else "• Artisanal Chocolates"

        order_receipt_text = (
            f"🍫 *CHOVIQUE — Order Confirmation*\n\n"
            f"Thank you for ordering with Chovique Luxury Chocolates!\n\n"
            f"📦 *Order ID:* {order.id}\n"
            f"📅 *Date:* {created_date}\n"
            f"💳 *Payment Method:* {order.payment_method or 'UPI'}\n"
            f"💰 *Total Amount:* ₹{float(order.total or 0.0):,.2f}\n"
            f"🚚 *Delivery:* {str(order.delivery_option or 'Standard Delivery')}\n\n"
            f"📍 *Shipping Address:*\n"
            f"{ship_addr.name}\n"
            f"{ship_addr.street}, {ship_addr.city}, {ship_addr.state} - {ship_addr.zip}\n"
            f"Phone: {ship_addr.phone}\n\n"
            f"✨ *Items:*\n{items_str}\n\n"
            f"For support, contact Chovique Concierge at +91 83098 54870 or hello@chovique.com."
        )
        encoded_receipt = urllib.parse.quote(order_receipt_text)
        customer_whatsapp_url = f"https://wa.me/{cust_phone_clean}?text={encoded_receipt}" if cust_phone_clean else None
        owner_whatsapp_url = f"https://wa.me/{owner_phone_clean}?text={encoded_receipt}" if owner_phone_clean else None

        return OrderResponse(
            id=str(order.id),
            items=cart_items,
            total=float(order.total or 0.0),
            subtotal=float(order.subtotal or 0.0),
            discount=float(order.discount or 0.0),
            coupon_code=order.coupon_code,
            coupon_discount=float(order.coupon_discount or 0.0),
            coins_used=int(order.coins_used or 0),
            coin_discount=float(order.coin_discount or 0.0),
            coins_earned=int(order.coins_earned or 0),
            shipping=float(order.shipping or 0.0),
            tax=float(order.tax or 0.0),
            date=created_date,
            status=str(order.status or "Processing"),
            payment_status=str(getattr(order, "payment_status", "PENDING") or "PENDING"),
            shippingAddress=ship_addr,
            deliveryOption=str(order.delivery_option or "Standard Delivery"),
            paymentMethod=str(order.payment_method or "UPI"),
            invoice_url=getattr(order, "invoice_url", None),
            user_id=getattr(order, "user_id", None),
            is_cancellable=is_cancellable,
            is_returnable=is_returnable,
            created_at=getattr(order, "created_at", None),
            delivered_at=getattr(order, "delivered_at", None),
            customer_whatsapp_url=customer_whatsapp_url,
            owner_whatsapp_url=owner_whatsapp_url,
        )

    # ==========================================================
    # Support Tickets
    # ==========================================================

    async def get_user_tickets(self, user_id: str) -> list[SupportTicketResponse]:
        tickets = await self.ticket_repo.get_user_tickets(user_id)
        return [self._format_ticket_response(t) for t in tickets]

    async def get_ticket_by_id(self, ticket_id: str, user_id: str) -> SupportTicketResponse | None:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket or ticket.customer_id != user_id:
            return None
        return self._format_ticket_response(ticket)

    async def create_ticket(self, user: User | str, payload: CreateTicketPayload) -> SupportTicketResponse:
        user_obj = user if isinstance(user, User) else await self.user_repo.get_by_id(user)
        if not user_obj:
            raise ValueError("User not found.")

        order_id_val = getattr(payload, "order_id", None) or getattr(payload, "orderId", None)
        linked_order_id = None
        if order_id_val and str(order_id_val).strip():
            clean_oid = str(order_id_val).strip()
            order = await self.order_repo.get_by_id(clean_oid)
            if not order or order.user_id != user_obj.id:
                raise ValueError("Selected order does not belong to you or does not exist.")
            linked_order_id = order.id

        ticket = await self.ticket_repo.create(
            customer_id=user_obj.id,
            customer_name=user_obj.full_name,
            category=payload.category,
            description=payload.description,
            order_id=linked_order_id,
            status="Pending",
        )

        # Create confirmation notification for customer
        await self.notification_repo.create(
            user_id=user_obj.id,
            type="support",
            title="Support Ticket Submitted",
            message=f"Support ticket #{ticket.id} received. Our team will update you shortly.",
            text=f"Support ticket #{ticket.id} received. Our team will update you shortly.",
            related_entity_type="support",
            related_entity_id=ticket.id,
            reference_id=ticket.id,
        )

        try:
            from app.services.notification_service import NotificationService
            await NotificationService(self.db).notify_support_message(
                ticket_id=ticket.id,
                user_name=user_obj.full_name,
                subject=f"{payload.category}: {payload.description[:40]}",
                commit=False
            )
        except Exception as notif_err:
            logger.warning("Failed to create admin notification for support ticket: %s", notif_err)

        try:
            import asyncio
            from app.integrations.resend import resend_email
            asyncio.create_task(
                resend_email.send_ticket_created(
                    email=user_obj.email,
                    name=user_obj.full_name or "Customer",
                    ticket_id=ticket.id,
                    category=ticket.category,
                    description=ticket.description,
                )
            )
        except Exception as e:
            logger.warning("Failed to dispatch ticket creation email: %s", e)

        return self._format_ticket_response(ticket)

    async def get_ticket_related_order(self, ticket_id: str, user: User) -> OrderResponse:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError("Support ticket not found.")

        # Security check: User must own the ticket (or be Admin)
        if user.role not in ["admin", "superadmin"] and ticket.customer_id != user.id:
            raise ValueError("Unauthorized access to ticket order details.")

        if not ticket.order_id:
            raise ValueError("No order is associated with this support ticket.")

        order = await self.order_repo.get_by_id(ticket.order_id)
        if not order:
            raise ValueError(f"Associated order '{ticket.order_id}' not found.")

        # Security check: User must own the order (or be Admin)
        if user.role not in ["admin", "superadmin"] and order.user_id != user.id:
            raise ValueError("Unauthorized access to order details.")

        return self._format_order_response(order)

    async def submit_ticket_feedback(
        self,
        ticket_id: str,
        user_id: str,
        feedback: str
    ) -> SupportTicketResponse:
        """Customer submits feedback on resolution satisfaction (Satisfied/Unsatisfied)."""
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError("Support ticket not found.")

        if ticket.customer_id != user_id:
            raise ValueError("Unauthorized to provide feedback for this ticket.")

        if ticket.status != "Resolved":
            raise ValueError("Feedback can only be provided for resolved support tickets.")

        ticket.customer_resolution_feedback = feedback
        await self.db.commit()
        await self.db.refresh(ticket)
        return self._format_ticket_response(ticket)

    async def acknowledge_ticket_notification(
        self,
        ticket_id: str,
        user_id: str
    ) -> SupportTicketResponse:
        """Acknowledge ticket notification and clear notified badge on ticket."""
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if not ticket:
            raise ValueError("Support ticket not found.")

        if ticket.customer_id != user_id:
            raise ValueError("Unauthorized to update this ticket.")

        ticket.notified = True
        await self.db.commit()
        await self.db.refresh(ticket)
        return self._format_ticket_response(ticket)

    def _format_ticket_response(self, ticket) -> SupportTicketResponse:
        created_date = ticket.created_at.strftime("%Y-%m-%d") if ticket.created_at else datetime.now().strftime("%Y-%m-%d")
        ord_id = getattr(ticket, "order_id", None)

        return SupportTicketResponse(
            id=ticket.id,
            customerId=ticket.customer_id,
            customerName=ticket.customer_name,
            category=ticket.category,
            description=ticket.description,
            status=ticket.status,
            orderId=ord_id,
            order_id=ord_id,
            adminNotes=None,
            customerResolutionFeedback=ticket.customer_resolution_feedback,
            date=created_date,
            notified=ticket.notified,
        )

    # ==========================================================
    # Notifications
    # ==========================================================

    async def get_user_notifications(self, user_id: str, is_read: bool | None = None) -> list[SupportNotificationResponse]:
        # Optionally auto-generate expiring coupon notifications for the customer
        try:
            from app.services.coupon_service import CouponService
            coupon_svc = CouponService(self.db)
            available_coupons = await coupon_svc.get_available_coupons(user_id)
            from datetime import timezone
            now_utc = datetime.now(timezone.utc)
            for c in available_coupons:
                if c.expires_at:
                    exp_dt = c.expires_at if c.expires_at.tzinfo else c.expires_at.replace(tzinfo=timezone.utc)
                    days_left = (exp_dt - now_utc).days
                    if 0 <= days_left <= 14:
                        date_str = exp_dt.strftime("%d-%m-%Y")
                        existing_notifs = await self.notification_repo.get_user_notifications(user_id)
                        already_notified = any(
                            n.type == "coupon" and n.reference_id == c.code
                            for n in existing_notifs
                        )
                        if not already_notified:
                            await self.notification_repo.create(
                                user_id=user_id,
                                type="coupon",
                                title="Coupon Expiring Soon",
                                message=f"Your {c.code} coupon expires on {date_str}.",
                                text=f"Your {c.code} coupon expires on {date_str}.",
                                related_entity_type="coupon",
                                related_entity_id=c.code,
                                reference_id=c.code,
                            )
        except Exception as e:
            logger.debug(f"Coupon expiring notification check: {e}")

        notifs = await self.notification_repo.get_user_notifications(user_id, is_read=is_read)
        res = []
        for n in notifs:
            title = n.title or (n.type.replace('_', ' ').title() if n.type else "Notification")
            msg = n.message or n.text or ""
            txt = n.text or n.message or title
            is_read_flag = bool(n.is_read or n.read)
            date_str = n.created_at.strftime("%d %b %Y") if n.created_at else datetime.now().strftime("%d %b %Y")
            res.append(
                SupportNotificationResponse(
                    id=n.id,
                    title=title,
                    message=msg,
                    text=txt,
                    date=date_str,
                    read=is_read_flag,
                    is_read=is_read_flag,
                    type=n.type or "general",
                    referenceId=n.reference_id or n.related_entity_id,
                    related_entity_type=n.related_entity_type,
                    related_entity_id=n.related_entity_id or n.reference_id,
                    created_at=n.created_at,
                )
            )
        return res

    async def get_user_unread_count(self, user_id: str) -> int:
        return await self.notification_repo.get_user_unread_count(user_id)

    async def mark_notification_read(self, user_id: str, notification_id: str) -> SupportNotificationResponse | None:
        notif = await self.notification_repo.mark_read(notification_id, user_id)
        if not notif:
            return None

        title = notif.title or (notif.type.replace('_', ' ').title() if notif.type else "Notification")
        msg = notif.message or notif.text or ""
        txt = notif.text or notif.message or title
        is_read_flag = bool(notif.is_read or notif.read)
        date_str = notif.created_at.strftime("%d %b %Y") if notif.created_at else datetime.now().strftime("%d %b %Y")

        return SupportNotificationResponse(
            id=notif.id,
            title=title,
            message=msg,
            text=txt,
            date=date_str,
            read=is_read_flag,
            is_read=is_read_flag,
            type=notif.type or "general",
            referenceId=notif.reference_id or notif.related_entity_id,
            related_entity_type=notif.related_entity_type,
            related_entity_id=notif.related_entity_id or notif.reference_id,
            created_at=notif.created_at,
        )

    async def mark_all_notifications_read(self, user_id: str) -> int:
        return await self.notification_repo.mark_user_read_all(user_id)

    async def delete_notification(self, user_id: str, notification_id: str) -> bool:
        return await self.notification_repo.delete(notification_id, user_id)

    # ==========================================================
    # Contact Form
    # ==========================================================

    async def submit_contact(
        self,
        payload: ContactMessageRequest,
    ) -> ContactMessageResponse:

        name = payload.name
        if not name:
            fname = payload.first_name or ""
            lname = payload.last_name or ""
            name = f"{fname} {lname}".strip() or "Anonymous"

        await self.contact_repo.create(
            name=name,
            email=payload.email,
            phone=payload.phone,
            subject=payload.subject,
            message=payload.message,
        )

        # Retrieve configured contact details (email, WhatsApp)
        contact_email = None
        owner_whatsapp = "+91 83098 54870"
        try:
            contact_data = await self.config_repo.get("contact")
            if contact_data and isinstance(contact_data, dict):
                contact_email = contact_data.get("email")
                owner_whatsapp = contact_data.get("whatsapp") or owner_whatsapp
        except Exception as cfg_err:
            logger.warning("Could not fetch contact configuration: %s", cfg_err)

        # Generate WhatsApp prefilled message and direct link to owner
        clean_phone = re.sub(r"\D", "", str(owner_whatsapp))
        wa_text = (
            f"🍫 *New Customer Inquiry - CHOVIQUE*\n\n"
            f"👤 *From:* {name}\n"
            f"✉️ *Email:* {payload.email}\n"
            f"📞 *Phone:* {payload.phone or 'Not provided'}\n"
            f"📋 *Subject:* {payload.subject or 'General Inquiry'}\n\n"
            f"💬 *Message:*\n{payload.message}\n"
        )
        whatsapp_url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(wa_text)}" if clean_phone else None

        # Build luxury HTML email notification for the company
        email_html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0705; color: #f5efe6; margin: 0; padding: 24px; }}
    .container {{ max-width: 600px; margin: 0 auto; background-color: #170f0b; border: 1px solid #c9a84c; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.6); }}
    .header {{ background-color: #231610; padding: 26px 20px; text-align: center; border-bottom: 1px solid rgba(201,168,76,0.3); }}
    .header h1 {{ color: #c9a84c; margin: 0; font-size: 22px; letter-spacing: 2px; text-transform: uppercase; }}
    .content {{ padding: 28px 24px; }}
    .row {{ margin-bottom: 18px; }}
    .label {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #c9a84c; margin-bottom: 6px; font-weight: 600; }}
    .value {{ font-size: 15px; color: #f5efe6; background: rgba(255,255,255,0.05); padding: 12px 14px; border-radius: 6px; border: 1px solid rgba(201,168,76,0.2); }}
    .msg-box {{ font-size: 15px; color: #f5efe6; background: rgba(255,255,255,0.07); padding: 16px; border-radius: 6px; border-left: 3px solid #c9a84c; line-height: 1.6; white-space: pre-wrap; }}
    .footer {{ padding: 16px 20px; text-align: center; font-size: 12px; color: rgba(245,239,230,0.6); border-top: 1px solid rgba(201,168,76,0.2); }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>New Customer Inquiry</h1>
    </div>
    <div class="content">
      <div class="row">
        <div class="label">Customer Name</div>
        <div class="value">{name}</div>
      </div>
      <div class="row">
        <div class="label">Email Address</div>
        <div class="value"><a href="mailto:{payload.email}" style="color: #c9a84c; text-decoration: none;">{payload.email}</a></div>
      </div>
      <div class="row">
        <div class="label">Phone Number</div>
        <div class="value">{payload.phone or 'Not provided'}</div>
      </div>
      <div class="row">
        <div class="label">Subject</div>
        <div class="value">{payload.subject or 'General Inquiry'}</div>
      </div>
      <div class="row">
        <div class="label">Message</div>
        <div class="msg-box">{payload.message}</div>
      </div>
    </div>
    <div class="footer">
      Sent from Chovique Chocolatier Contact Concierge
    </div>
  </div>
</body>
</html>
"""
        # Collect distinct recipients for company notification
        recipients = list(dict.fromkeys(filter(None, [
            contact_email,
            getattr(settings, "SUPERADMIN_EMAIL", None),
            getattr(settings, "MAIL_FROM", None),
        ])))
        if not recipients:
            recipients = ["support@chovique.com"]

        for recipient in recipients:
            try:
                await MailService.send_generic_email(
                    email=recipient,
                    subject=f"[Chovique Inquiry] {payload.subject or 'Customer Message'} from {name}",
                    html_content=email_html,
                    context_label="Customer Contact Inquiry",
                )
            except Exception as mail_err:
                logger.error("Failed to send contact inquiry email to %s: %s", recipient, mail_err)

        return ContactMessageResponse(
            message="Thanks — we'll get back to you within 24 hours.",
            whatsapp_url=whatsapp_url,
        )

    # ==========================================================
    # Product Reviews
    # ==========================================================
    # Product Reviews & Purchase Verification
    # ==========================================================

    async def verify_user_purchased_product(self, user_id: str, product_id: str) -> bool:
        """
        Check if user has an order containing product_id with status != 'Cancelled'.
        """
        if not user_id:
            return False
        from sqlalchemy import func, select
        from app.models.order import Order, OrderItem

        result = await self.db.execute(
            select(func.count())
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.user_id == user_id,
                OrderItem.product_id == product_id,
                Order.status != "Cancelled",
            )
        )
        return (result.scalar() or 0) > 0

    async def get_product_reviews(self, product_id: str) -> list[ReviewResponse]:
        reviews = await self.review_repo.get_product_reviews(product_id, status="approved")
        return [
            ReviewResponse(
                id=r.id,
                author=r.author,
                rating=r.rating,
                text=r.text,
                date=r.created_at.strftime("%Y-%m-%d") if r.created_at else datetime.now().strftime("%Y-%m-%d"),
                avatar=r.avatar,
            )
            for r in reviews
        ]

    async def get_product_reviews_with_summary(self, product_id: str) -> dict:
        reviews = await self.get_product_reviews(product_id)
        summary = await self.review_repo.get_rating_summary(product_id)
        return {
            "reviews": reviews,
            "average_rating": summary["average_rating"],
            "total_reviews": summary["total_reviews"],
            "star_breakdown": summary["star_breakdown"],
        }

    async def create_product_review(
        self,
        product_id: str,
        author: str,
        rating: float,
        text: str,
        user_id: str | None = None,
        bypass_purchase_check: bool = False,
    ) -> dict:

        # 1. Purchase Verification
        if user_id and not bypass_purchase_check:
            purchased = await self.verify_user_purchased_product(user_id, product_id)
            if not purchased:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You can only review products you have purchased."
                )

        initials = "".join([w[0].upper() for w in author.split()[:2]]) if author else "U"

        # 2. Create Review
        review = await self.review_repo.create(
            product_id=product_id,
            user_id=user_id,
            author=author,
            rating=rating,
            text=text,
            avatar=initials,
            status="approved",
        )

        # 3. Recalculate Average Rating & Total Ratings Count for Product
        summary = await self.review_repo.get_rating_summary(product_id)
        await self.product_repo.update(
            product_id,
            rating=summary["average_rating"],
            ratings_count=summary["total_reviews"],
        )

        return {
            "id": review.id,
            "author": review.author,
            "rating": review.rating,
            "text": review.text,
            "date": review.created_at.strftime("%Y-%m-%d") if review.created_at else datetime.now().strftime("%Y-%m-%d"),
            "avatar": review.avatar,
            "summary": summary,
        }

