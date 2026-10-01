import logging
from typing import Optional, List, Dict, Any
import httpx
from app.core.config import settings
from app.services.email_template import (
    render_luxury_email,
    build_welcome_template,
    build_order_confirmation_template,
    build_shipping_template,
    build_delivery_partner_assigned_template,
    build_out_for_delivery_template,
    build_delivered_template,
    build_cancellation_template,
    build_refund_template,
    build_coins_template,
    build_ticket_template,
    build_generic_notification_template,
)

logger = logging.getLogger(__name__)


class ResendEmailIntegration:
    """
    Resend API Integration for transactional emails.
    Sends emails using Resend REST API if API key is configured,
    or logs in dev mode.
    """

    def __init__(self):
        self.api_key = settings.RESEND_API_KEY
        self.from_email = settings.MAIL_FROM or "Chovique Chocolatier <onboarding@resend.dev>"
        self.platform_name = getattr(settings, "PROJECT_NAME", "Chovique Chocolatier")
        self.api_url = "https://api.resend.com/emails"

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        context_label: str = "Notification",
    ) -> bool:
        """Send a single email via existing MailService infrastructure."""
        try:
            from app.services.mail_service import MailService
            return await MailService.send_generic_email(
                email=to_email,
                subject=subject,
                html_content=html_content,
                context_label=context_label,
            )
        except Exception as e:
            logger.error("Failed to send %s email to %s: %s", context_label, to_email, e)
            return False

    # ==========================================================
    # 1. SUPER ADMIN EMAIL NOTIFICATIONS
    # ==========================================================

    async def send_superadmin_new_admin(self, super_admin_email: str, super_admin_name: str, admin_name: str, admin_email: str, created_at: str):
        subject = "New Admin Account Created"
        rows = [
            ("Admin Name", admin_name),
            ("Admin Email", admin_email),
            ("Created On", created_at),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="New Admin Staff Onboarded",
            recipient_name=super_admin_name,
            badge_text="Staff Management",
            body_paragraphs=[
                f"A new administrator account has been created on <strong>{self.platform_name}</strong>.",
                "Please review their permission profile from the Admin Console if any role adjustments are needed.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_admin_activated(self, super_admin_email: str, super_admin_name: str, admin_name: str, admin_email: str, activated_at: str):
        subject = "Admin Account Activated"
        rows = [
            ("Admin Name", admin_name),
            ("Admin Email", admin_email),
            ("Activated On", activated_at),
            ("Status", "Active"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Admin Account Activated",
            recipient_name=super_admin_name,
            badge_text="Account Activated",
            body_paragraphs=[
                f"The administrative account for <strong>{admin_name}</strong> ({admin_email}) has been successfully activated.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_admin_deactivated(self, super_admin_email: str, super_admin_name: str, admin_name: str, admin_email: str, deactivated_at: str):
        subject = "Admin Account Deactivated"
        rows = [
            ("Admin Name", admin_name),
            ("Admin Email", admin_email),
            ("Deactivated On", deactivated_at),
            ("Status", "Deactivated"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Admin Account Deactivated",
            recipient_name=super_admin_name,
            badge_text="Account Deactivated",
            body_paragraphs=[
                f"The administrator account for <strong>{admin_name}</strong> ({admin_email}) has been deactivated.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_admin_updated(self, super_admin_email: str, super_admin_name: str, admin_name: str, admin_email: str, updated_at: str):
        subject = "Admin Profile Updated"
        rows = [
            ("Admin Name", admin_name),
            ("Admin Email", admin_email),
            ("Updated On", updated_at),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Admin Profile Changed",
            recipient_name=super_admin_name,
            badge_text="Profile Update",
            body_paragraphs=[
                f"The profile details for admin <strong>{admin_name}</strong> ({admin_email}) were updated.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_admin_password_updated(self, super_admin_email: str, super_admin_name: str, admin_name: str, admin_email: str, updated_at: str):
        subject = "Admin Password Updated"
        rows = [
            ("Admin Name", admin_name),
            ("Admin Email", admin_email),
            ("Updated On", updated_at),
            ("Security Action", "Password Reset / Changed"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Admin Credential Update",
            recipient_name=super_admin_name,
            badge_text="Security Notice",
            body_paragraphs=[
                f"The access password for administrator <strong>{admin_email}</strong> was updated.",
                "If this activity was not authorized, please lock the account immediately.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_security_alert(self, super_admin_email: str, super_admin_name: str, admin_email: str, security_event: str, detected_at: str):
        subject = "Admin Security Alert"
        rows = [
            ("Admin Account", admin_email),
            ("Security Event", security_event),
            ("Detected On", detected_at),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Platform Security Alert",
            recipient_name=super_admin_name,
            badge_text="Security Alert",
            body_paragraphs=[
                f"A security event was logged on the administrative console for account <strong>{admin_email}</strong>.",
                "Please review recent audit logs and IP sessions to ensure platform integrity.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    async def send_superadmin_platform_alert(self, super_admin_email: str, super_admin_name: str, alert_title: str, alert_message: str, occurred_at: str):
        subject = f"Critical Platform Alert: {alert_title}"
        rows = [
            ("Alert Title", alert_title),
            ("Occurred On", occurred_at),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline=f"Critical Alert: {alert_title}",
            recipient_name=super_admin_name,
            badge_text="Critical System Event",
            body_paragraphs=[
                alert_message,
                "Immediate administrator review recommended.",
            ],
            key_values=rows,
        )
        return await self.send_email(super_admin_email, subject, html)

    # ==========================================================
    # 2. ADMIN EMAIL NOTIFICATIONS
    # ==========================================================

    async def send_admin_new_order(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, order_total: float, payment_status: str, order_date: str):
        subject = f"New Order Received – #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer Name", customer_name),
            ("Total Amount", f"₹{order_total:,.2f}"),
            ("Payment Status", payment_status.title()),
            ("Order Date", order_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="New Customer Order Placed",
            recipient_name=admin_name,
            badge_text="New Order",
            body_paragraphs=[
                f"A new order <strong>#{order_id}</strong> has been received from <strong>{customer_name}</strong>.",
                "Please review items and assign for artisanal preparation.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_payment_success(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, amount: float, payment_method: str, payment_date: str):
        subject = f"Payment Successful – Order #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer", customer_name),
            ("Amount", f"₹{amount:,.2f}"),
            ("Payment Method", payment_method),
            ("Payment Date", payment_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Customer Payment Captured",
            recipient_name=admin_name,
            badge_text="Payment Success",
            body_paragraphs=[
                f"Payment of <strong>₹{amount:,.2f}</strong> for order <strong>#{order_id}</strong> was captured successfully.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_payment_failure(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, amount: float, payment_method: str, failure_reason: str):
        subject = f"Payment Failed – Order #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer", customer_name),
            ("Attempted Amount", f"₹{amount:,.2f}"),
            ("Method", payment_method),
            ("Failure Reason", failure_reason or "Declined"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Order Payment Declined",
            recipient_name=admin_name,
            badge_text="Payment Failed",
            body_paragraphs=[
                f"Payment attempt for order <strong>#{order_id}</strong> failed.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_order_cancelled(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, order_total: float, cancelled_at: str, cancellation_reason: str):
        subject = f"Order Cancelled – #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer", customer_name),
            ("Order Total", f"₹{order_total:,.2f}"),
            ("Cancelled On", cancelled_at or "Today"),
            ("Reason", cancellation_reason or "Customer/Admin action"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Order Has Been Cancelled",
            recipient_name=admin_name,
            badge_text="Order Cancelled",
            body_paragraphs=[
                f"Order <strong>#{order_id}</strong> was cancelled.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_refund_initiated(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, refund_amount: float, refund_reason: str, initiated_at: str):
        subject = f"Refund Initiated – Order #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer", customer_name),
            ("Refund Amount", f"₹{refund_amount:,.2f}"),
            ("Reason", refund_reason or "N/A"),
            ("Initiated On", initiated_at or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Refund Process Initiated",
            recipient_name=admin_name,
            badge_text="Refund Initiated",
            body_paragraphs=[
                f"A refund of <strong>₹{refund_amount:,.2f}</strong> was initiated for order #{order_id}.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_refund_completed(self, admin_email: str, admin_name: str, order_id: str, customer_name: str, refund_amount: float, refund_date: str):
        subject = f"Refund Completed – Order #{order_id}"
        rows = [
            ("Order ID", f"#{order_id}"),
            ("Customer", customer_name),
            ("Refund Amount", f"₹{refund_amount:,.2f}"),
            ("Completed On", refund_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Refund Successfully Processed",
            recipient_name=admin_name,
            badge_text="Refund Completed",
            body_paragraphs=[
                f"The refund of <strong>₹{refund_amount:,.2f}</strong> for order #{order_id} has completed.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_low_stock(self, admin_email: str, admin_name: str, product_name: str, product_sku: str, current_stock: int, threshold: int = 10):
        subject = f"Low Stock Alert – {product_name}"
        rows = [
            ("Product Name", product_name),
            ("SKU", product_sku),
            ("Current Stock", str(current_stock)),
            ("Alert Threshold", str(threshold)),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Inventory Alert: Low Stock",
            recipient_name=admin_name,
            badge_text="Low Stock Warning",
            body_paragraphs=[
                f"Artisanal product <strong>{product_name}</strong> has dropped to <strong>{current_stock}</strong> units.",
                "Please coordinate with chocolatiers for a fresh production batch.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_out_of_stock(self, admin_email: str, admin_name: str, product_name: str, product_sku: str, updated_at: str):
        subject = f"Out of Stock – {product_name}"
        rows = [
            ("Product Name", product_name),
            ("SKU", product_sku),
            ("Stock Level", "0 Units (Depleted)"),
            ("Depleted On", updated_at or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Inventory Alert: Out of Stock",
            recipient_name=admin_name,
            badge_text="Out of Stock",
            body_paragraphs=[
                f"Product <strong>{product_name}</strong> is now completely out of stock on the storefront.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_offline_sale(self, admin_email: str, admin_name: str, transaction_id: str, company_name: str, transaction_amount: float, payment_method: str, transaction_date: str):
        subject = f"New Offline Sale – #{transaction_id}"
        rows = [
            ("Transaction ID", f"#{transaction_id}"),
            ("Client / Corporate", company_name),
            ("Amount", f"₹{transaction_amount:,.2f}"),
            ("Payment Method", payment_method),
            ("Date", transaction_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="New Corporate / Offline Sale Recorded",
            recipient_name=admin_name,
            badge_text="B2B Offline Sale",
            body_paragraphs=[
                f"A new offline sale has been registered for <strong>{company_name}</strong>.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_offline_sale_update(self, admin_email: str, admin_name: str, transaction_id: str, company_name: str, transaction_amount: float, status: str, updated_at: str):
        subject = f"Offline Sale {status.capitalize()} – #{transaction_id}"
        rows = [
            ("Transaction ID", f"#{transaction_id}"),
            ("Client / Corporate", company_name),
            ("Amount", f"₹{transaction_amount:,.2f}"),
            ("Status", status.title()),
            ("Updated On", updated_at or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline=f"Offline Sale {status.capitalize()}",
            recipient_name=admin_name,
            badge_text=f"Sale {status.capitalize()}",
            body_paragraphs=[
                f"Offline transaction <strong>#{transaction_id}</strong> for {company_name} was marked as {status}.",
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_support_request(self, admin_email: str, admin_name: str, customer_name: str, customer_email: str, support_subject: str, support_message: str, created_at: str):
        subject = f"New Customer Support Request: {support_subject}"
        rows = [
            ("Customer Name", customer_name),
            ("Customer Email", customer_email),
            ("Subject", support_subject),
            ("Submitted On", created_at or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="New Customer Support Request",
            recipient_name=admin_name,
            badge_text="Support Ticket",
            body_paragraphs=[
                f"A customer inquiry has been submitted by <strong>{customer_name}</strong>:",
                f'<div style="background-color: #FAF7F2; border-left: 3px solid #D4AF37; padding: 12px 16px; margin: 12px 0; font-style: italic; color: #2D2421;">{support_message}</div>',
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_product_alert(self, admin_email: str, admin_name: str, product_name: str, product_sku: str, alert_message: str, alert_date: str):
        subject = f"Product Alert – {product_name}"
        rows = [
            ("Product", product_name),
            ("SKU", product_sku),
            ("Alert Date", alert_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline=f"Product Alert: {product_name}",
            recipient_name=admin_name,
            badge_text="Product Alert",
            body_paragraphs=[
                alert_message,
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    async def send_admin_coupon_alert(self, admin_email: str, admin_name: str, coupon_code: str, coupon_name: str, alert_message: str, alert_date: str):
        subject = f"Coupon Alert – {coupon_code}"
        rows = [
            ("Coupon Code", coupon_code),
            ("Coupon Name", coupon_name),
            ("Date", alert_date or "Today"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline=f"Coupon Alert: {coupon_code}",
            recipient_name=admin_name,
            badge_text="Coupon Alert",
            body_paragraphs=[
                alert_message,
            ],
            key_values=rows,
        )
        return await self.send_email(admin_email, subject, html)

    # ==========================================================
    # 3. CUSTOMER EMAIL NOTIFICATIONS (LUXURY RESPONSIVE)
    # ==========================================================

    async def send_welcome(self, email: str, name: str):
        subject = f"Welcome to {self.platform_name} – Pure Artisanal Indulgence"
        html = build_welcome_template(name=name, email=email)
        return await self.send_email(email, subject, html, context_label="Welcome")

    async def send_order_confirmation(
        self,
        email: str,
        name: str,
        order_id: str,
        total: float,
        order_date: str = "",
        payment_status: str = "Pending",
        payment_method: str = "Online Payment",
        items_html: str = "",
        delivery_option: str = "Standard Delivery",
    ):
        subject = f"Order Confirmed – #{order_id}"
        html = build_order_confirmation_template(
            name=name,
            order_id=order_id,
            total=total,
            order_date=order_date,
            payment_status=payment_status,
            payment_method=payment_method,
            items_html=items_html,
            delivery_option=delivery_option,
        )
        return await self.send_email(email, subject, html, context_label="Order confirmation")

    async def send_payment_successful(self, email: str, name: str, order_id: str, amount: float, payment_method: str, payment_date: str):
        subject = f"Payment Successful – Order #{order_id}"
        base_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        rows = [
            ("Order Reference", f"#{order_id}"),
            ("Amount Paid", f"₹{amount:,.2f}"),
            ("Payment Method", payment_method),
            ("Payment Date", payment_date or "Today"),
            ("Status", "Successful / Verified"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Payment Confirmed!",
            recipient_name=name,
            badge_text="✓ Payment Successful",
            body_paragraphs=[
                f"We have received your payment of <strong>₹{amount:,.2f}</strong> for order <strong>#{order_id}</strong>.",
                "Your order has moved to our boutique kitchen for artisan preparation.",
            ],
            key_values=rows,
            cta_text="Track Your Order",
            cta_url=f"{base_url}/dashboard",
        )
        return await self.send_email(email, subject, html, context_label="Payment success")

    async def send_payment_failed(self, email: str, name: str, order_id: str, amount: float, failure_reason: str):
        subject = f"Payment Incomplete – Order #{order_id}"
        base_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        rows = [
            ("Order Reference", f"#{order_id}"),
            ("Attempted Amount", f"₹{amount:,.2f}"),
            ("Reason", failure_reason or "Declined by bank / network"),
            ("Status", "Action Required"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Payment Could Not Be Completed",
            recipient_name=name,
            badge_text="Payment Pending",
            body_paragraphs=[
                f"We were unable to process the payment for order <strong>#{order_id}</strong>.",
                "Your handcrafted selection is currently reserved for you in your dashboard. You may complete the payment using UPI, Cards, or Netbanking.",
            ],
            key_values=rows,
            cta_text="Complete Payment Now",
            cta_url=f"{base_url}/dashboard",
        )
        return await self.send_email(email, subject, html, context_label="Payment failure")

    async def send_order_processing(self, email: str, name: str, order_id: str):
        subject = f"Your Order Is Being Prepared – #{order_id}"
        base_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        rows = [
            ("Order Reference", f"#{order_id}"),
            ("Status", "Master Chocolatier Handcrafting"),
            ("Packaging", "Insulated Climate-Controlled Box"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Your Chocolates Are Being Handcrafted",
            recipient_name=name,
            badge_text="🍫 Kitchen Preparation",
            body_paragraphs=[
                f"Your order <strong>#{order_id}</strong> is now in our artisan atelier.",
                "Our chocolatiers are assembling your fresh batch using single-origin cacao and signature ganache recipes.",
                "You will receive live courier tracking details as soon as your box is sealed and dispatched.",
            ],
            key_values=rows,
            cta_text="View Order in Dashboard",
            cta_url=f"{base_url}/dashboard",
        )
        return await self.send_email(email, subject, html, context_label="Order processing")

    async def send_shipping_update(
        self,
        email: str,
        name: str,
        order_id: str,
        tracking_number: str = "",
        courier_name: str = "Standard Shipping",
        estimated_delivery: str = "3-5 Business Days",
    ):
        subject = f"Your Order Has Been Dispatched! – #{order_id}"
        html = build_shipping_template(
            name=name,
            order_id=order_id,
            tracking_number=tracking_number,
            courier_name=courier_name,
            estimated_delivery=estimated_delivery,
        )
        return await self.send_email(email, subject, html, context_label="Order shipped")

    async def send_out_for_delivery(
        self,
        email: str,
        name: str,
        order_id: str,
        delivery_otp: str = "",
        delivery_boy_name: str = "",
        delivery_boy_phone: str = "",
        estimated_delivery: str = "Today",
    ):
        subject = f"Out for Delivery Today! (OTP Inside) – #{order_id}"
        html = build_out_for_delivery_template(
            name=name,
            order_id=order_id,
            delivery_otp=delivery_otp,
            delivery_boy_name=delivery_boy_name,
            delivery_boy_phone=delivery_boy_phone,
            estimated_delivery=estimated_delivery,
        )
        return await self.send_email(email, subject, html, context_label="Out for delivery")

    async def send_delivery_partner_assigned(
        self,
        email: str,
        name: str,
        order_id: str,
        delivery_boy_name: str = "Chovique Specialist",
        delivery_boy_phone: str = "",
        estimated_delivery: str = "Today",
    ):
        subject = f"Delivery Partner Assigned – Order #{order_id}"
        html = build_delivery_partner_assigned_template(
            name=name,
            order_id=order_id,
            delivery_boy_name=delivery_boy_name,
            delivery_boy_phone=delivery_boy_phone,
            estimated_delivery=estimated_delivery,
        )
        return await self.send_email(email, subject, html, context_label="Delivery partner assigned")

    async def send_order_delivered(
        self,
        email: str,
        name: str,
        order_id: str,
        delivered_at: str = "",
        payment_method: str = "UPI",
        payment_status: str = "Paid",
        order_total: float = 0.0,
        order_items_html: str = "",
    ):
        subject = f"Delivered: Your Chovique Chocolates Have Arrived – #{order_id}"
        html = build_delivered_template(
            name=name,
            order_id=order_id,
            delivery_date=delivered_at or "Today",
        )
        return await self.send_email(email, subject, html, context_label="Order delivered")

    async def send_cancellation(
        self,
        email: str,
        name: str,
        order_id: str,
        cancellation_reason: str = "Customer Request",
        order_total: float = 0.0,
        order_date: str = "",
        cancelled_at: str = "",
        payment_method: str = "UPI",
        payment_status: str = "Cancelled",
        order_items_html: str = "",
    ):
        subject = f"Order Cancelled – #{order_id}"
        html = build_cancellation_template(
            name=name,
            order_id=order_id,
            order_total=order_total,
            cancellation_reason=cancellation_reason,
        )
        return await self.send_email(email, subject, html, context_label="Order cancellation")

    async def send_return_request(
        self,
        email: str,
        name: str,
        order_id: str,
        return_requested_at: str = "",
        return_reason: str = "Customer Request",
        return_items_html: str = "",
    ):
        subject = f"Return Request Received – #{order_id}"
        base_url = getattr(settings, "FRONTEND_URL", "http://localhost:5173")
        rows = [
            ("Order Reference", f"#{order_id}"),
            ("Requested On", return_requested_at or "Today"),
            ("Reason", return_reason or "Customer request"),
            ("Status", "Under Concierge Review"),
        ]
        html = build_generic_notification_template(
            subject=subject,
            headline="Return Request Acknowledged",
            recipient_name=name,
            badge_text="Return Requested",
            body_paragraphs=[
                f"We have received your return request for order <strong>#{order_id}</strong>.",
                "Because our confections are perishable luxury items, our concierge team reviews all inquiries within 24 hours to ensure quality standards.",
            ],
            key_values=rows,
            cta_text="Check Ticket in Dashboard",
            cta_url=f"{base_url}/dashboard",
        )
        return await self.send_email(email, subject, html, context_label="Return request")

    async def send_refund_initiated(self, email: str, name: str, order_id: str, refund_amount: float, initiated_at: str):
        subject = f"Refund Initiated – Order #{order_id}"
        html = build_refund_template(
            name=name,
            order_id=order_id,
            amount=refund_amount,
            status="Initiated",
        )
        return await self.send_email(email, subject, html, context_label="Refund initiated")

    async def send_refund_notification(self, email: str, name: str, order_id: str, amount: float, refund_date: str = "", refund_reference: str = ""):
        subject = f"Refund Completed – Order #{order_id}"
        html = build_refund_template(
            name=name,
            order_id=order_id,
            amount=amount,
            reference=refund_reference,
            status="Completed",
        )
        return await self.send_email(email, subject, html, context_label="Refund")

    async def send_coins_credited(self, email: str, name: str, coins_earned: int, coin_balance: int, credited_at: str):
        subject = "Chovique Reward Coins Added to Your Account!"
        html = build_coins_template(
            name=name,
            event_type="earned",
            coins=coins_earned,
            balance=coin_balance,
        )
        return await self.send_email(email, subject, html, context_label="Coins credit")

    async def send_coins_used(self, email: str, name: str, coins_used: int, coin_balance: int, order_id: str):
        subject = f"Chovique Coins Applied to Order #{order_id}"
        html = build_coins_template(
            name=name,
            event_type="used",
            coins=coins_used,
            balance=coin_balance,
            order_id=order_id,
        )
        return await self.send_email(email, subject, html, context_label="Coins used")

    async def send_coins_restored(self, email: str, name: str, coins_restored: int, coin_balance: int, restored_at: str):
        subject = "Chovique Reward Coins Restored"
        html = build_coins_template(
            name=name,
            event_type="restored",
            coins=coins_restored,
            balance=coin_balance,
        )
        return await self.send_email(email, subject, html, context_label="Coins restored")

    async def send_ticket_created(self, email: str, name: str, ticket_id: str, category: str, description: str, created_at: str = ""):
        subject = f"Support Request Received – #{ticket_id[:8]}"
        html = build_ticket_template(
            name=name,
            ticket_id=ticket_id[:8],
            subject_text=category,
            status="Open",
            message=description,
            is_update=False,
        )
        return await self.send_email(email, subject, html, context_label="Support ticket created")

    async def send_ticket_updated(self, email: str, name: str, ticket_id: str, support_subject: str, status: str, support_response: str):
        subject = f"Update on Support Request #{ticket_id[:8]}"
        html = build_ticket_template(
            name=name,
            ticket_id=ticket_id[:8],
            subject_text=support_subject,
            status=status,
            message=support_response,
            is_update=True,
        )
        return await self.send_email(email, subject, html, context_label="Support ticket updated")


resend_email = ResendEmailIntegration()
