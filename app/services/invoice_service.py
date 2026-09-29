import datetime
import html
import logging
from typing import Optional
from app.models.order import Order

logger = logging.getLogger(__name__)

class InvoiceService:
    @staticmethod
    def generate_html_invoice(order: Order, user_name: str, user_email: str) -> str:
        safe_user_name = html.escape(str(user_name or "Customer"))
        safe_user_email = html.escape(str(user_email or ""))

        items_html = ""
        for item in getattr(order, "items", []) or []:
            raw_product_name = item.product.name if item.product else "Chovique Product"
            product_name = html.escape(str(raw_product_name))
            price = item.price or 0.0
            quantity = item.quantity or 1
            line_total = price * quantity
            items_html += f"""
            <tr>
                <td style="padding: 12px 10px; border-bottom: 1px solid #eee;">{product_name}</td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #eee; text-align: center;">{quantity}</td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #eee; text-align: right;">₹{price:.2f}</td>
                <td style="padding: 12px 10px; border-bottom: 1px solid #eee; text-align: right;">₹{line_total:.2f}</td>
            </tr>
            """
            
        shipping_address = order.shipping_address or {}
        addr_name = html.escape(str(shipping_address.get('name') or safe_user_name))
        addr_street = html.escape(str(shipping_address.get('street') or ''))
        addr_city = html.escape(str(shipping_address.get('city') or ''))
        addr_state = html.escape(str(shipping_address.get('state') or ''))
        addr_zip = html.escape(str(shipping_address.get('zip') or shipping_address.get('zip_code') or ''))
        addr_phone = html.escape(str(shipping_address.get('phone') or 'N/A'))

        address_html = f"""
        <strong>{addr_name}</strong><br>
        {addr_street}<br>
        {addr_city}, {addr_state} {addr_zip}<br>
        Phone: {addr_phone}
        """

        coupon_code_safe = html.escape(str(order.coupon_code or 'CODE'))
        coupon_discount_row = ""
        if getattr(order, "coupon_discount", 0) and order.coupon_discount > 0:
            coupon_discount_row = f"""
            <tr>
                <td colspan="3" style="text-align: right; padding: 8px 10px; color: #555;">Coupon Discount ({coupon_code_safe})</td>
                <td style="text-align: right; padding: 8px 10px; color: #e74c3c;">-₹{order.coupon_discount:.2f}</td>
            </tr>
            """

        coin_discount_row = ""
        if getattr(order, "coin_discount", 0) and order.coin_discount > 0:
            coin_discount_row = f"""
            <tr>
                <td colspan="3" style="text-align: right; padding: 8px 10px; color: #555;">Reward Coins Discount</td>
                <td style="text-align: right; padding: 8px 10px; color: #e74c3c;">-₹{order.coin_discount:.2f}</td>
            </tr>
            """

        general_discount_row = ""
        if order.discount > 0:
            general_discount_row = f"""
            <tr>
                <td colspan="3" style="text-align: right; padding: 8px 10px; color: #555;">Special Discount</td>
                <td style="text-align: right; padding: 8px 10px; color: #e74c3c;">-₹{order.discount:.2f}</td>
            </tr>
            """

        created_str = (
            order.created_at.strftime('%b %d, %Y')
            if getattr(order, 'created_at', None)
            else datetime.date.today().strftime('%b %d, %Y')
        )
        payment_method = getattr(order, 'payment_method', 'UPI') or 'UPI'
        order_status = getattr(order, 'status', 'Processing') or 'Processing'
        payment_status = getattr(order, 'payment_status', 'Pending') or 'Pending'

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Invoice - {order.id}</title>
    <style>
        body {{
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            color: #2c2c2c;
            margin: 0;
            padding: 0;
            background-color: #f4f1ea;
        }}
        .invoice-box {{
            max-width: 800px;
            margin: 30px auto;
            padding: 40px;
            border: 1px solid #e0d7c6;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.08);
            background-color: #ffffff;
            font-size: 15px;
            line-height: 22px;
            border-radius: 8px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        table td {{
            padding: 6px;
            vertical-align: top;
        }}
        .header-table {{
            margin-bottom: 30px;
            border-bottom: 2px solid #d4af37;
            padding-bottom: 20px;
        }}
        .brand-title {{
            font-size: 32px;
            letter-spacing: 2px;
            color: #1a0d00;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .brand-subtitle {{
            font-size: 12px;
            color: #d4af37;
            letter-spacing: 3px;
            text-transform: uppercase;
            margin-top: 4px;
        }}
        .info-table {{
            margin-bottom: 30px;
        }}
        .items-table {{
            margin-bottom: 20px;
        }}
        .items-table th {{
            background: #1a0d00;
            color: #d4af37;
            border-bottom: 2px solid #d4af37;
            font-weight: 600;
            padding: 12px 10px;
            text-transform: uppercase;
            font-size: 13px;
            letter-spacing: 1px;
        }}
        .totals-row td {{
            border-top: 2px solid #1a0d00;
            font-weight: bold;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            background: #eafaf1;
            color: #2ecc71;
            border: 1px solid #2ecc71;
        }}
        @media print {{
            body {{ background-color: #fff; }}
            .invoice-box {{ box-shadow: none; border: none; margin: 0; padding: 0; }}
            .no-print {{ display: none !important; }}
        }}
    </style>
</head>
<body>
    <div class="invoice-box">
        <table class="header-table">
            <tr>
                <td>
                    <div class="brand-title">CHOVIQUE</div>
                    <div class="brand-subtitle">Artisanal Chocolatier & Confectionery</div>
                </td>
                <td style="text-align: right;">
                    <strong style="font-size: 18px; color: #1a0d00;">TAX INVOICE</strong><br>
                    <span style="color: #666;">Invoice #: <strong>INV-{order.id}</strong></span><br>
                    <span style="color: #666;">Order Reference: <strong>{order.id}</strong></span><br>
                    <span style="color: #666;">Date: {created_str}</span>
                </td>
            </tr>
        </table>
        
        <table class="info-table">
            <tr>
                <td style="width: 50%;">
                    <strong style="color: #d4af37; text-transform: uppercase; font-size: 13px; letter-spacing: 1px;">Customer Details:</strong><br>
                    <strong>{user_name}</strong><br>
                    {user_email}<br>
                    <br>
                    <strong>Payment Method:</strong> {payment_method}<br>
                    <strong>Payment Status:</strong> <span class="badge">{payment_status}</span>
                </td>
                <td style="width: 50%; text-align: right;">
                    <strong style="color: #d4af37; text-transform: uppercase; font-size: 13px; letter-spacing: 1px;">Shipping / Delivery Address:</strong><br>
                    {address_html}<br>
                    <strong>Order Status:</strong> {order_status}
                </td>
            </tr>
        </table>
        
        <table class="items-table">
            <thead>
                <tr>
                    <th>Product / Item</th>
                    <th style="text-align: center;">Qty</th>
                    <th style="text-align: right;">Unit Price</th>
                    <th style="text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
                
                <tr class="totals-row">
                    <td colspan="3" style="text-align: right; padding: 10px;">Subtotal</td>
                    <td style="text-align: right; padding: 10px;">₹{order.subtotal:.2f}</td>
                </tr>
                {general_discount_row}
                {coupon_discount_row}
                {coin_discount_row}
                <tr>
                    <td colspan="3" style="text-align: right; padding: 8px 10px; color: #555;">Shipping Charges</td>
                    <td style="text-align: right; padding: 8px 10px;">₹{order.shipping:.2f}</td>
                </tr>
                <tr>
                    <td colspan="3" style="text-align: right; padding: 8px 10px; color: #555;">Tax (GST)</td>
                    <td style="text-align: right; padding: 8px 10px;">₹{order.tax:.2f}</td>
                </tr>
                <tr style="font-size: 1.25em; background: #faf8f5;">
                    <td colspan="3" style="text-align: right; padding: 12px 10px; border-top: 2px solid #1a0d00; border-bottom: 2px solid #1a0d00; color: #1a0d00;"><strong>Grand Total Paid</strong></td>
                    <td style="text-align: right; padding: 12px 10px; border-top: 2px solid #1a0d00; border-bottom: 2px solid #1a0d00; color: #d4af37;"><strong>₹{order.total:.2f}</strong></td>
                </tr>
            </tbody>
        </table>
        
        <div style="text-align: center; margin-top: 40px; color: #777; font-size: 13px; border-top: 1px solid #eee; padding-top: 20px;">
            Thank you for indulging with <strong>Chovique Chocolatier</strong>!<br>
            For any assistance, contact us at <em>support@chovique.com</em>.<br>
            <a href="javascript:window.print()" style="color: #1a0d00; background: #d4af37; text-decoration: none; display: inline-block; margin-top: 15px; padding: 8px 24px; border-radius: 4px; font-weight: bold;" class="no-print">Print / Save Invoice</a>
        </div>
    </div>
</body>
</html>"""
        return html

    @classmethod
    async def generate_and_upload_invoice(cls, order: Order, user_name: str, user_email: str) -> Optional[str]:
        """
        Generate HTML invoice and upload to S3 storage.
        Returns the secure S3 URL or None if upload fails/disabled.
        """
        try:
            from app.services.storage_service import storage_service
            html_content = cls.generate_html_invoice(order, user_name, user_email)
            html_bytes = html_content.encode("utf-8")
            
            filename = f"INV-{order.id}"
            secure_url = await storage_service.upload_bytes(
                file_bytes=html_bytes,
                filename=filename,
                folder="chocolate-world/invoices",
                resource_type="raw",
            )
            logger.info("Successfully uploaded invoice for order %s to S3 storage: %s", order.id, secure_url)
            return secure_url
        except Exception as e:
            logger.warning("Failed to upload invoice to S3 storage for order %s: %s", order.id, e)
            return None

