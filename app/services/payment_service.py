import logging
from typing import Dict, Any
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.razorpay import razorpay_client
from app.integrations.resend import resend_email
from app.repositories.cart_repository import CartRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.product_repository import ProductRepository
from app.repositories.user_repository import UserRepository
from app.schemas.payment import VerifyPaymentPayload

logger = logging.getLogger(__name__)


class PaymentService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.payment_repo = PaymentRepository(db)
        self.order_repo = OrderRepository(db)
        self.product_repo = ProductRepository(db)
        self.cart_repo = CartRepository(db)
        self.user_repo = UserRepository(db)

    async def verify_payment(
        self,
        user_id: str,
        payload: VerifyPaymentPayload,
    ) -> Dict[str, Any]:
        """
        Verify Razorpay payment signature & update database safely.
        Enforces double-processing protection and ownership validation.
        """
        return await self.finalize_online_payment(
            razorpay_order_id=payload.razorpay_order_id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_signature=payload.razorpay_signature,
            user_id=user_id,
        )

    async def finalize_online_payment(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str | None = None,
        user_id: str | None = None,
    ) -> Dict[str, Any]:
        """
        Canonical idempotent order-finalization mechanism shared by:
        1. Client-side /payments/verify
        2. Razorpay webhook payment.captured
        """
        logger.info(
            "Finalizing online payment for razorpay_order_id=%s, payment_id=%s",
            razorpay_order_id,
            razorpay_payment_id,
        )

        payment = await self.payment_repo.get_by_razorpay_order_id(razorpay_order_id)
        if not payment:
            raise ValueError("Payment transaction record not found.")

        # Payment ownership / IDOR validation
        if user_id and payment.user_id != user_id:
            logger.warning("Payment ownership mismatch: payment user=%s, auth user=%s", payment.user_id, user_id)
            raise ValueError("Unauthorized payment transaction access.")

        # Idempotency / Double-processing protection
        if payment.status == "captured":
            logger.info("Payment %s already captured. Idempotent return success.", razorpay_order_id)
            return {
                "success": True,
                "message": "Payment already verified.",
                "order_id": payment.order_id,
            }

        # Verify Razorpay signature if provided (e.g. from client callback)
        if razorpay_signature:
            is_valid = razorpay_client.verify_payment_signature(
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
            )

            if not is_valid:
                await self.payment_repo.update_status(
                    razorpay_order_id=razorpay_order_id,
                    status="failed",
                    razorpay_payment_id=razorpay_payment_id,
                    error_message="Invalid Razorpay payment signature.",
                )
                raise ValueError("Payment signature verification failed.")

        # Update Payment record status
        await self.payment_repo.update_status(
            razorpay_order_id=razorpay_order_id,
            status="captured",
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature or payment.razorpay_signature,
        )

        # Fetch Order & Finalize
        order = await self.order_repo.get_by_id(payment.order_id)
        if order and order.payment_status != "PAID":
            order.payment_status = "PAID"
            order.paid_at = func.now()
            order.status = "Processing"

            # Atomic Inventory Deduction
            for item in getattr(order, "items", []) or []:
                if item.product_id and item.quantity > 0:
                    deducted = await self.product_repo.deduct_stock_atomic(
                        item.product_id, item.quantity, commit=False
                    )
                    if not deducted:
                        logger.warning(
                            "Insufficient stock during payment finalization for product %s", item.product_id
                        )

            # Wallet rewards (Redeem used & Earn new - strictly customers only)
            try:
                from app.models.user import User
                pay_user = await self.db.get(User, payment.user_id)
                if pay_user and pay_user.role == "customer":
                    from app.services.wallet_service import WalletService
                    wallet_service = WalletService(self.db)

                    if getattr(order, "coins_used", 0) and order.coins_used > 0:
                        await wallet_service.redeem_coins(
                            user_id=payment.user_id,
                            order_id=order.id,
                            coins=order.coins_used,
                            commit=False,
                        )

                    coins_earned, _ = await wallet_service.earn_coins(
                        user_id=payment.user_id,
                        order_id=order.id,
                        payable_amount=order.total,
                        commit=False,
                    )
                    order.coins_earned = coins_earned
                else:
                    order.coins_used = 0
                    order.coins_earned = 0
            except Exception as exc:
                logger.error("Failed to process wallet rewards during finalization: %s", exc)

            # Coupon Usage Recording
            if getattr(order, "coupon_code", None) and getattr(order, "coupon_discount", 0) > 0:
                try:
                    from app.models.coupon import CouponUsage, Coupon
                    from sqlalchemy import select, func, update
                    coupon_res = await self.db.execute(
                        select(Coupon).where(Coupon.code == order.coupon_code)
                    )
                    coupon = coupon_res.scalar_one_or_none()
                    if coupon:
                        usage_check = await self.db.execute(
                            select(func.count(CouponUsage.id)).where(
                                CouponUsage.coupon_id == coupon.id,
                                CouponUsage.order_id == order.id,
                            )
                        )
                        if (usage_check.scalar() or 0) == 0:
                            self.db.add(
                                CouponUsage(
                                    coupon_id=coupon.id,
                                    user_id=payment.user_id,
                                    order_id=order.id,
                                    discount_amount=order.coupon_discount or 0.0,
                                )
                            )
                except Exception as exc:
                    logger.error("Failed to record coupon usage during payment finalization: %s", exc)

            # Clear user cart & wishlist
            try:
                user_cart = await self.cart_repo.get_or_create_user_cart(payment.user_id, commit=False)
                from app.repositories.wishlist_repository import WishlistRepository
                wishlist_repo = WishlistRepository(self.db)
                for item in getattr(order, "items", []) or []:
                    await self.cart_repo.remove_item(user_cart.id, item.product_id, commit=False)
                    await self.wishlist_repo.remove_item(payment.user_id, item.product_id, commit=False) if hasattr(self, "wishlist_repo") else await wishlist_repo.remove_item(payment.user_id, item.product_id, commit=False)
            except Exception as exc:
                logger.error("Failed clearing cart/wishlist during payment finalization: %s", exc)

            await self.db.commit()

            # Send Email Confirmation (non-blocking background dispatch)
            try:
                import asyncio
                user = await self.user_repo.get_by_id(payment.user_id)
                if user and user.email:
                    items_html = ""
                    try:
                        if hasattr(order, "items") and order.items:
                            for it in order.items:
                                p_name = getattr(it.product, "name", "Artisanal Chocolate") if getattr(it, "product", None) else "Artisanal Chocolate"
                                items_html += f"<li><strong>{p_name}</strong> × {it.quantity} — ₹{it.price * it.quantity:,.2f}</li>"
                    except Exception:
                        pass

                    asyncio.create_task(
                        resend_email.send_order_confirmation(
                            email=user.email,
                            name=user.full_name or "Valued Customer",
                            order_id=order.id,
                            total=order.total,
                            payment_status=order.payment_status,
                            payment_method=order.payment_method or "Razorpay / UPI",
                            items_html=items_html,
                            delivery_option=getattr(order, "delivery_option", "Standard Delivery") or "Standard Delivery",
                        )
                    )
            except Exception as e:
                logger.warning("Failed triggering email confirmation for order %s: %s", order.id, e)

            # Generate Invoice
            try:
                from app.services.invoice_service import InvoiceService
                user = await self.user_repo.get_by_id(payment.user_id)
                user_name = user.full_name if user else "Customer"
                user_email = user.email if user else ""
                inv_url = await InvoiceService.generate_and_upload_invoice(order, user_name, user_email)
                if inv_url:
                    order.invoice_url = inv_url
                    await self.db.commit()
            except Exception as e:
                logger.warning("Failed invoice generation for order %s: %s", order.id, e)

        return {
            "success": True,
            "message": "Payment verified successfully.",
            "order_id": payment.order_id,
        }
