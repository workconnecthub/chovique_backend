import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.razorpay import razorpay_client
from app.repositories.address_repository import AddressRepository
from app.repositories.cart_repository import CartRepository
from app.repositories.coupon_repository import CouponRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.order import OrderPayload, OrderResponse, ShippingAddressSchema

logger = logging.getLogger(__name__)


class CheckoutService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cart_repo = CartRepository(db)
        self.product_repo = ProductRepository(db)
        self.coupon_repo = CouponRepository(db)
        self.address_repo = AddressRepository(db)
        self.order_repo = OrderRepository(db)
        self.payment_repo = PaymentRepository(db)

    async def initiate_checkout(
        self,
        user_id: str,
        payload: OrderPayload,
    ) -> Dict[str, Any]:
        """
        100% server-side checkout engine.
        1. Validate stock & live prices for all items.
        2. Validate shipping address.
        3. Validate coupon conditions (expiry, min order, max discount).
        4. Calculate tax & shipping costs.
        5. Create Pending Order in database.
        6. Initiate Razorpay Order & register Payment attempt.
        7. Return Razorpay Order ID & checkout summary to client.
        """
        logger.info("Initiating checkout for user %s", user_id)

        items_to_process = payload.items
        if not items_to_process:
            user_cart = await self.cart_repo.get_or_create_user_cart(user_id, commit=False)
            items_to_process = [
                type("CartItemPayload", (), {"product_id": ci.product_id, "quantity": ci.quantity})()
                for ci in (getattr(user_cart, "items", []) or [])
            ]

        if not items_to_process:
            raise ValueError("Checkout items list cannot be empty.")

        subtotal = 0.0
        items_data = []

        # Step 1: Validate stock & prices server-side
        for item in items_to_process:
            product = await self.product_repo.get_by_id(item.product_id)
            if not product or not product.is_active or getattr(product, "is_available", True) is False:
                raise ValueError(f"Product '{item.product_id}' is unavailable.")

            if product.stock < item.quantity:
                raise ValueError(f"Insufficient stock for '{product.name}'. Only {product.stock} left.")

            unit_price = product.price
            subtotal += unit_price * item.quantity
            items_data.append({
                "product_id": product.id,
                "quantity": item.quantity,
                "price": unit_price,
            })

        # Step 2: Validate coupon server-side
        discount = 0.0
        if payload.coupon_code:
            from app.services.coupon_service import CouponService
            coupon_service = CouponService(self.db)
            coupon_res = await coupon_service.validate_coupon(
                code=payload.coupon_code,
                subtotal=subtotal,
                user_id=user_id,
            )
            if coupon_res.valid:
                discount = coupon_res.discount_amount or 0.0
            else:
                logger.warning("Coupon %s invalid during checkout initiation: %s", payload.coupon_code, coupon_res.message)
                raise ValueError(coupon_res.message or "Invalid or inapplicable coupon code.")

        # Step 3: Coin redemption validation
        coins_used = 0
        coin_discount = 0.0
        if getattr(payload, "coins_to_use", 0) and payload.coins_to_use > 0:
            from app.services.wallet_service import WalletService
            wallet_service = WalletService(self.db)
            redemption_calc = await wallet_service.calculate_redemption(
                user_id=user_id,
                subtotal=subtotal,
                coupon_discount=discount,
                coins_requested=payload.coins_to_use,
            )
            if redemption_calc.user_balance < payload.coins_to_use:
                raise ValueError(f"Insufficient coin balance. Available: {redemption_calc.user_balance} coins.")
            if redemption_calc.allowed_coins > 0:
                coins_used = redemption_calc.allowed_coins
                coin_discount = redemption_calc.coin_discount

        # Step 4: Validate serviceability & calculate authoritative shipping fee
        from app.services.fulfillment_routing_service import FulfillmentRoutingService
        from app.repositories.platform_settings_repository import PlatformSettingsRepository

        shipping_addr_dict = payload.shipping_address.model_dump()
        dest_pincode = shipping_addr_dict.get("zip") or ""

        routing_service = FulfillmentRoutingService(self.db)
        shipping_res = await routing_service.calculate_shipping(
            pincode=dest_pincode,
            cart_total=subtotal,
            city=shipping_addr_dict.get("city"),
            state=shipping_addr_dict.get("state"),
            latitude=shipping_addr_dict.get("latitude"),
            longitude=shipping_addr_dict.get("longitude"),
        )

        if not shipping_res.serviceable:
            raise ValueError(shipping_res.message or "Sorry, delivery is currently unavailable for this location.")

        shipping = float(shipping_res.delivery_charge)
        ps_repo = PlatformSettingsRepository(self.db)
        ps = await ps_repo.get()

        tax = round(subtotal * (ps.gst_rate / 100.0), 2)
        total_discount = discount + coin_discount
        total = max(0.0, subtotal - total_discount + shipping + tax)
        total_rounded = round(total, 2)

        # Step 5: Create Pending Order in DB with authoritative snapshot
        order = await self.order_repo.create_order(
            user_id=user_id,
            total=total_rounded,
            subtotal=round(subtotal, 2),
            discount=round(total_discount, 2),
            shipping=round(shipping, 2),
            tax=round(tax, 2),
            shipping_address=shipping_addr_dict,
            delivery_option=payload.delivery_option or f"{shipping_res.fulfillment_type.capitalize()} Delivery",
            payment_method=payload.payment_method,
            items_data=items_data,
            coupon_code=payload.coupon_code if discount > 0 else None,
            coupon_discount=round(discount, 2),
            coins_used=coins_used,
            coin_discount=round(coin_discount, 2),
            fulfillment_type=shipping_res.fulfillment_type,
            shipping_provider=shipping_res.shipping_provider,
            fulfillment_status="UNASSIGNED",
            store_location_id=shipping_res.origin_store_id,
            shipping_snapshot=shipping_addr_dict,
        )


        # Step 6: Initiate Razorpay Order
        razorpay_order = razorpay_client.create_order(
            amount=total_rounded,
            currency="INR",
            receipt=order.id,
            notes={"user_id": user_id, "order_id": order.id},
        )

        # Step 7: Create Payment record in DB
        payment = await self.payment_repo.create_payment(
            order_id=order.id,
            user_id=user_id,
            razorpay_order_id=razorpay_order.get("id"),
            amount=total_rounded,
            currency="INR",
        )

        return {
            "order_id": order.id,
            "razorpay_order_id": razorpay_order.get("id"),
            "amount": razorpay_order.get("amount"),  # in paise for Razorpay frontend SDK
            "currency": "INR",
            "key_id": razorpay_client.key_id,
            "subtotal": subtotal,
            "discount": total_discount,
            "shipping": shipping,
            "tax": tax,
        }
