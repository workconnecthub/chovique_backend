"""
Chovique Luxury Email Template System
Responsive, mobile-optimized HTML email templates with embedded brand assets.
Designed to look stunning on mobile phones, tablets, and desktop/laptop screens.
"""

from typing import Optional, List, Tuple, Dict, Any
from app.core.config import settings


def _get_base_url() -> str:
    """Return frontend base URL."""
    return getattr(settings, "FRONTEND_URL", "http://localhost:5173")


def render_luxury_email(
    *,
    subject: str,
    headline: str,
    recipient_name: str,
    body_paragraphs: List[str],
    badge_text: Optional[str] = None,
    badge_bg: str = "#E8F8F0",
    badge_color: str = "#1B7F45",
    summary_card_rows: Optional[List[Tuple[str, str]]] = None,
    highlight_box_html: Optional[str] = None,
    items_html: Optional[str] = None,
    cta_text: Optional[str] = None,
    cta_url: Optional[str] = None,
    secondary_cta_text: Optional[str] = None,
    secondary_cta_url: Optional[str] = None,
    tip_note: Optional[str] = None,
    footer_note: Optional[str] = None,
) -> str:
    """
    Renders an ultra-luxurious, fully responsive email for Chovique Artisanal Chocolates.
    Uses CID:chovique_banner and CID:chovique_logo for embedded, flicker-free brand imagery.
    """
    base_url = _get_base_url()
    store_name = "Chovique Chocolatier"

    # 1. Badge Pill
    badge_section = ""
    if badge_text:
        badge_section = f"""
        <div style="text-align: center; margin-bottom: 20px;">
          <span style="display: inline-block; background-color: {badge_bg}; color: {badge_color}; font-size: 12px; font-weight: 700; padding: 6px 18px; border-radius: 20px; text-transform: uppercase; letter-spacing: 1px;">
            {badge_text}
          </span>
        </div>
        """

    # 2. Greeting & Paragraphs
    paragraphs_html = ""
    if recipient_name:
        paragraphs_html += f'<p style="margin: 0 0 16px 0; font-size: 15px; line-height: 1.65; color: #2D2421;">Hello <strong style="color: #1E100A;">{recipient_name}</strong>,</p>'
    for p in body_paragraphs:
        paragraphs_html += f'<p style="margin: 0 0 14px 0; font-size: 15px; line-height: 1.65; color: #4A3E39;">{p}</p>'

    # 3. Summary Card Rows
    summary_card_html = ""
    if summary_card_rows:
        rows_str = ""
        total_index = len(summary_card_rows) - 1
        for idx, (label, val) in enumerate(summary_card_rows):
            is_last = (idx == total_index)
            border_css = "" if is_last else "border-bottom: 1px solid #EAE3D9;"
            font_size = "15px" if is_last else "14px"
            font_weight = "700" if is_last else "600"
            color = "#A0522D" if is_last else "#1E100A"

            rows_str += f"""
            <tr>
              <td style="{border_css} padding: 10px 12px; font-size: 13px; color: #7A6D66;">{label}</td>
              <td align="right" style="{border_css} padding: 10px 12px; font-size: {font_size}; font-weight: {font_weight}; color: {color};">{val}</td>
            </tr>
            """
        summary_card_html = f"""
        <table class="email-detail-table" width="100%" cellpadding="0" cellspacing="0" style="background-color: #FAF7F2; border-radius: 10px; border: 1px solid #EAE3D9; margin: 20px 0;">
          {rows_str}
        </table>
        """

    # 4. Highlight Box (e.g. OTP code or highlight stats)
    highlight_html = ""
    if highlight_box_html:
        highlight_html = f"""
        <div style="margin: 24px 0; text-align: center;">
          {highlight_box_html}
        </div>
        """

    # 5. Items Section (for orders)
    items_section = ""
    if items_html and items_html.strip():
        items_section = f"""
        <div style="margin-top: 20px; padding-top: 18px; border-top: 1px solid #EAE3D9;">
          <h3 style="margin: 0 0 12px 0; font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px; color: #1E100A; font-weight: 700;">Artisanal Selections</h3>
          <ul style="margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.8; color: #4A3E39;">
            {items_html}
          </ul>
        </div>
        """

    # 6. Interactive CTA Button(s)
    cta_html = ""
    if cta_text and cta_url:
        cta_html = f"""
        <div style="margin: 28px 0 16px 0; text-align: center;">
          <a href="{cta_url}" class="email-btn" target="_blank" style="display: inline-block; background: linear-gradient(135deg, #1E100A 0%, #3D1C06 100%); color: #D4AF37; text-decoration: none; padding: 15px 36px; border-radius: 8px; font-size: 15px; font-weight: 700; letter-spacing: 1px; border: 1px solid #D4AF37; box-shadow: 0 4px 14px rgba(30, 16, 10, 0.25); text-transform: uppercase;">
            {cta_text}
          </a>
        </div>
        """
        if secondary_cta_text and secondary_cta_url:
            cta_html += f"""
            <div style="margin: 0 0 20px 0; text-align: center;">
              <a href="{secondary_cta_url}" target="_blank" style="font-size: 13px; color: #A0522D; text-decoration: underline; font-weight: 600;">
                {secondary_cta_text} →
              </a>
            </div>
            """

    # 7. Tip Note (Gold/Chocolate Accent Box)
    tip_box_html = ""
    if tip_note:
        tip_box_html = f"""
        <div style="background-color: #FDFBF7; border-left: 4px solid #D4AF37; border-radius: 0 8px 8px 0; padding: 14px 18px; margin: 22px 0;">
          <p style="margin: 0; font-size: 13px; line-height: 1.5; color: #4A3E39;">
            {tip_note}
          </p>
        </div>
        """

    # 8. Footer Note / Disclaimer
    footer_note_str = footer_note or "Thank you for choosing Chovique Chocolatier for your artisanal indulgence."

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <title>{subject}</title>
  <style type="text/css">
    /* Client Resets */
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    table, td {{ mso-table-lspace: 0pt; mso-table-rspace: 0pt; }}
    img {{ -ms-interpolation-mode: bicubic; border: 0; outline: none; text-decoration: none; }}
    body {{ margin: 0; padding: 0; width: 100% !important; background-color: #F4EFEA; }}

    /* Responsive Mobile Rules */
    @media only screen and (max-width: 600px) {{
      .email-wrapper {{ padding: 12px 8px !important; }}
      .email-container {{ width: 100% !important; max-width: 100% !important; border-radius: 8px !important; }}
      .email-content {{ padding: 24px 16px !important; }}
      .email-hero-img {{ width: 100% !important; height: auto !important; border-radius: 8px 8px 0 0 !important; }}
      .email-heading {{ font-size: 20px !important; line-height: 26px !important; }}
      .email-btn {{ display: block !important; width: 100% !important; box-sizing: border-box !important; padding: 14px 20px !important; font-size: 14px !important; text-align: center !important; }}
      .email-detail-table td {{ padding: 9px 8px !important; font-size: 13px !important; }}
      .email-otp-box {{ padding: 14px 20px !important; }}
      .email-otp-code {{ font-size: 26px !important; letter-spacing: 6px !important; }}
    }}
  </style>
</head>
<body style="margin: 0; padding: 0; background-color: #F4EFEA; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #2D2421;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="email-wrapper" style="background-color: #F4EFEA; padding: 32px 16px;">
    <tr>
      <td align="center">
        <!-- Main Card Container -->
        <table role="presentation" class="email-container" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width: 580px; background-color: #FFFFFF; border-radius: 14px; overflow: hidden; box-shadow: 0 8px 30px rgba(30, 16, 10, 0.08); border: 1px solid #E7DEC8;">
          
          <!-- Master Luxury Brand Banner -->
          <tr>
            <td style="background-color: #060504; padding: 0; text-align: center; border-bottom: 2px solid #D4AF37; line-height: 0;">
              <a href="{base_url}" target="_blank" style="display: block; text-decoration: none; line-height: 0;">
                <img src="https://images.unsplash.com/photo-1548907040-4d42b52115ca?auto=format&fit=crop&w=600&q=80" alt="Chovique Chocolatier" class="email-hero-img" style="width: 100%; max-width: 580px; height: auto; display: block; margin: 0 auto; border-top-left-radius: 13px; border-top-right-radius: 13px;" />
              </a>
            </td>
          </tr>

          <!-- Main Content Area -->
          <tr>
            <td class="email-content" style="padding: 36px 32px 28px 32px;">
              {badge_section}

              <h2 class="email-heading" style="margin: 0 0 18px 0; font-size: 22px; font-weight: 700; color: #1E100A; text-align: center;">
                {headline}
              </h2>

              {paragraphs_html}

              {highlight_html}

              {summary_card_html}

              {items_section}

              {cta_html}

              {tip_box_html}

              <hr style="border: none; border-top: 1px solid #EAE3D9; margin: 28px 0 20px 0;" />

              <!-- Signoff -->
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td>
                    <p style="margin: 0; font-size: 14px; line-height: 1.6; color: #4A3E39;">
                      With warm regards,<br/>
                      <strong style="color: #1E100A;">The Chovique Chocolatier Concierge</strong>
                    </p>
                  </td>
                  <td align="right">
                    <span style="font-size: 22px;">🍫✨</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer Area -->
          <tr>
            <td style="background-color: #F8F5F0; padding: 24px 20px; text-align: center; border-top: 1px solid #EAE3D9;">
              <p style="margin: 0 0 8px 0; font-size: 12px; font-weight: 600; color: #7A6D66;">
                {store_name} &bull; Pure Handcrafted Indulgence
              </p>
              <p style="margin: 0 0 10px 0; font-size: 11px; line-height: 1.5; color: #9A8D86;">
                {footer_note_str}
              </p>
              <div style="margin-top: 12px;">
                <a href="{base_url}" target="_blank" style="font-size: 11px; color: #A0522D; text-decoration: none; margin: 0 8px; font-weight: 600;">Visit Boutique</a> &bull;
                <a href="{base_url}/dashboard" target="_blank" style="font-size: 11px; color: #A0522D; text-decoration: none; margin: 0 8px; font-weight: 600;">My Account</a> &bull;
                <a href="{base_url}/contact" target="_blank" style="font-size: 11px; color: #A0522D; text-decoration: none; margin: 0 8px; font-weight: 600;">Contact Concierge</a>
              </div>
              <p style="margin: 14px 0 0 0; font-size: 10px; color: #B3A8A0;">
                &copy; 2026 Chovique Chocolatier. All rights reserved.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


# ============================================================================
# SPECIALIZED LUXURY TEMPLATE BUILDERS
# ============================================================================

def build_otp_template(
    *,
    name: str,
    otp: str,
    heading: str,
    body_text: str,
    footer_note: str,
    expiry_minutes: int = 5,
) -> str:
    """Build a responsive OTP email with glowing luxury gold display box."""
    otp_box_html = f"""
    <div class="email-otp-box" style="display: inline-block; background-color: #1E100A; border: 2px solid #D4AF37; border-radius: 10px; padding: 16px 40px; box-shadow: 0 4px 16px rgba(30,16,10,0.18);">
      <span class="email-otp-code" style="font-family: 'Courier New', Courier, monospace; font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #D4AF37; display: block; margin-left: 8px;">
        {otp}
      </span>
    </div>
    <p style="margin: 14px 0 0 0; font-size: 13px; color: #7A6D66;">
      ⏱️ This verification code expires in <strong>{expiry_minutes} minutes</strong>.
    </p>
    """
    return render_luxury_email(
        subject=heading,
        headline=heading,
        recipient_name=name,
        badge_text="🔒 Security Verification",
        badge_bg="#FFF8E1",
        badge_color="#B78103",
        body_paragraphs=[body_text],
        highlight_box_html=otp_box_html,
        tip_note="Never share your verification code with anyone. Our concierge will never ask for your code.",
        footer_note=footer_note,
    )


def build_welcome_template(*, name: str, email: str) -> str:
    """Build a rich welcome email with boutique invite and CTA."""
    base_url = _get_base_url()
    return render_luxury_email(
        subject="Welcome to Chovique Chocolatier",
        headline="Welcome to the World of Chovique",
        recipient_name=name,
        badge_text="✨ Royal Member Welcome",
        badge_bg="#E8F8F0",
        badge_color="#1B7F45",
        body_paragraphs=[
            "We are thrilled to welcome you to our artisanal community of chocolate connoisseurs.",
            "Each of our handcrafted confections is curated from single-origin cacao, infused with premium botanicals and finished by hand in small batches.",
            f"Your account (<strong>{email}</strong>) is now active. You are now eligible for exclusive tasting releases, member rewards, and concierge services.",
        ],
        cta_text="Explore Boutique Collections",
        cta_url=f"{base_url}/shop",
        secondary_cta_text="View Your Customer Dashboard",
        secondary_cta_url=f"{base_url}/dashboard",
        tip_note="🍫 <strong>Chocolatier's Tip:</strong> Store your artisanal chocolates between 16°C and 19°C away from direct sunlight for the optimal velvety snap.",
        footer_note="You received this email because you created an account with Chovique Chocolatier.",
    )


def build_order_confirmation_template(
    *,
    name: str,
    order_id: str,
    total: float,
    order_date: str = "Today",
    payment_status: str = "Pending",
    payment_method: str = "Online Payment",
    items_html: str = "",
    delivery_option: str = "Standard Delivery",
) -> str:
    """Build a high-end order confirmation email with breakdown card and CTA."""
    base_url = _get_base_url()
    p_status = str(payment_status or "Pending").strip()
    if p_status.upper() in ("PAID", "COMPLETED", "SUCCESSFUL"):
        badge_text = "✓ Order Confirmed & Paid"
        badge_bg = "#E8F8F0"
        badge_color = "#1B7F45"
    else:
        badge_text = f"Order Placed ({p_status.title()})"
        badge_bg = "#FFF8E1"
        badge_color = "#B78103"

    rows = [
        ("Order Reference", f"#{order_id}"),
        ("Order Date", order_date or "Today"),
        ("Payment Method", payment_method),
        ("Payment Status", p_status.title()),
        ("Delivery Method", delivery_option),
        ("Total Amount", f"₹{total:,.2f}"),
    ]

    return render_luxury_email(
        subject=f"Order Confirmed – #{order_id}",
        headline="Thank You for Your Order!",
        recipient_name=name,
        badge_text=badge_text,
        badge_bg=badge_bg,
        badge_color=badge_color,
        body_paragraphs=[
            "Your artisanal chocolate order has been placed successfully. Our master chocolatiers are preparing your collection with utmost precision and care.",
        ],
        summary_card_rows=rows,
        items_html=items_html,
        cta_text="Track Order Status",
        cta_url=f"{base_url}/dashboard",
        secondary_cta_text="View Full Order in Dashboard",
        secondary_cta_url=f"{base_url}/dashboard",
        tip_note="🍫 <strong>Handcrafted Freshness:</strong> We pack every order in insulated, climate-controlled packaging so your confections arrive in pristine boutique condition.",
        footer_note="Need assistance with your order? Our concierge is available 7 days a week.",
    )


def build_shipping_template(
    *,
    name: str,
    order_id: str,
    tracking_number: str = "",
    courier_name: str = "Standard Shipping",
    estimated_delivery: str = "3-5 Business Days",
) -> str:
    """Build a shipping confirmation email with tracking details."""
    base_url = _get_base_url()
    display_tracking = tracking_number or f"CHV-TRK-{order_id[-6:]}"
    rows = [
        ("Order Reference", f"#{order_id}"),
        ("Carrier / Courier", courier_name),
        ("Tracking Number", display_tracking),
        ("Estimated Delivery", estimated_delivery),
    ]

    return render_luxury_email(
        subject=f"Your Order Has Been Dispatched! – #{order_id}",
        headline="Your Chocolates Are On Their Way!",
        recipient_name=name,
        badge_text="🚚 Dispatched & In Transit",
        badge_bg="#E8F8F0",
        badge_color="#1B7F45",
        body_paragraphs=[
            f"Delightful news! Your handcrafted chocolate collection for order <strong>#{order_id}</strong> has departed our boutique and is currently en route to you.",
        ],
        summary_card_rows=rows,
        cta_text="Track Live Shipment",
        cta_url=f"{base_url}/dashboard",
        tip_note="📦 <strong>Climate-Safe Delivery:</strong> Your package is temperature-sealed. Please ensure someone is present to receive the delivery so it isn't left in ambient heat.",
        footer_note="Live tracking updates can take up to 2-4 hours to reflect on the carrier network.",
    )


def build_delivery_partner_assigned_template(
    *,
    name: str,
    order_id: str,
    delivery_boy_name: str = "Chovique Specialist",
    delivery_boy_phone: str = "",
    estimated_delivery: str = "Today",
) -> str:
    """Build an email notifying customer that a delivery partner has been assigned and accepted."""
    base_url = _get_base_url()
    rows = [
        ("Order ID", f"#{order_id}"),
        ("Delivery Executive", delivery_boy_name or "Chovique Specialist"),
    ]
    if delivery_boy_phone:
        rows.append(("Executive Contact", delivery_boy_phone))
    rows.append(("Fulfillment Status", "Assigned & Accepted"))
    rows.append(("Estimated Delivery", estimated_delivery))

    return render_luxury_email(
        subject=f"Delivery Partner Assigned – Order #{order_id}",
        headline="Your Order is in Expert Hands",
        recipient_name=name,
        badge_text="🚴 Delivery Partner Assigned",
        badge_bg="#EBF5FB",
        badge_color="#2980B9",
        body_paragraphs=[
            f"Wonderful news! Your order <strong>#{order_id}</strong> has been assigned to and accepted by our delivery partner <strong>{delivery_boy_name}</strong>.",
            "They will be collecting your chilled, artisanal confections shortly to ensure they arrive in flawless condition.",
        ],
        summary_card_rows=rows,
        cta_text="View Order in Dashboard",
        cta_url=f"{base_url}/dashboard?tab=orders&order_id={order_id}",
        tip_note="🍫 When your delivery partner heads to your doorstep, a secure 6-digit Delivery OTP will be generated for package verification.",
    )


def build_out_for_delivery_template(
    *,
    name: str,
    order_id: str,
    delivery_otp: str = "",
    delivery_boy_name: str = "",
    delivery_boy_phone: str = "",
    estimated_delivery: str = "Today",
) -> str:
    """Build an out-for-delivery alert email with prominent OTP."""
    base_url = _get_base_url()
    rows = [
        ("Order ID", f"#{order_id}"),
    ]
    if delivery_boy_name:
        rows.append(("Delivery Executive", delivery_boy_name))
    if delivery_boy_phone:
        rows.append(("Executive Phone", delivery_boy_phone))
    rows.append(("Fulfillment Status", "Out for Delivery"))
    rows.append(("Estimated Arrival", estimated_delivery))

    highlight_html = ""
    if delivery_otp:
        otp_digits = " ".join(list(delivery_otp))
        highlight_html = f"""
        <div class="email-otp-box" style="background: #FFF8E7; border: 2px dashed #D4AF37; border-radius: 12px; padding: 20px 24px; display: inline-block; max-width: 380px;">
          <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 2px; color: #8A6D3B; font-weight: 700; margin-bottom: 8px;">Delivery Verification OTP</div>
          <div class="email-otp-code" style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #1E100A; font-family: monospace;">{otp_digits}</div>
          <div style="font-size: 12px; color: #7A6D66; margin-top: 8px;">Please share this confidential 6-digit OTP with your delivery executive upon package handover.</div>
        </div>
        """

    return render_luxury_email(
        subject=f"Out for Delivery Today! (OTP Inside) – #{order_id}",
        headline="Pure Indulgence Arrives Today!",
        recipient_name=name,
        badge_text="⚡ Out for Delivery",
        badge_bg="#FFF8E1",
        badge_color="#B78103",
        body_paragraphs=[
            f"The delivery partner has collected your package for order <strong>#{order_id}</strong> and is out for delivery in your area.",
            f"Your order is scheduled for arrival: <strong>{estimated_delivery}</strong>.",
        ],
        highlight_box_html=highlight_html,
        summary_card_rows=rows,
        cta_text="View Delivery Details & OTP",
        cta_url=f"{base_url}/dashboard?tab=orders&order_id={order_id}",
        tip_note="🔒 <strong>Security Notice:</strong> Only provide your OTP once you receive your chilled Chovique packaging at your doorstep.",
    )


def build_delivered_template(
    *,
    name: str,
    order_id: str,
    delivery_date: str = "Today",
) -> str:
    """Build a delivered celebration email with review prompt."""
    base_url = _get_base_url()
    return render_luxury_email(
        subject=f"Delivered: Your Chovique Chocolates Have Arrived – #{order_id}",
        headline="Your Handcrafted Chocolates Have Arrived",
        recipient_name=name,
        badge_text="✓ Successfully Delivered",
        badge_bg="#E8F8F0",
        badge_color="#1B7F45",
        body_paragraphs=[
            f"Your order <strong>#{order_id}</strong> has been delivered on <strong>{delivery_date}</strong>.",
            "We hope each bite brings you a moment of pure bliss. Take your time to savor the delicate balance of aromas, silky textures, and complex single-origin notes.",
        ],
        cta_text="Leave a Tasting Review",
        cta_url=f"{base_url}/dashboard",
        secondary_cta_text="Reorder Your Favorites",
        secondary_cta_url=f"{base_url}/shop",
        tip_note="✨ <strong>Share Your Moment:</strong> Tag @ChoviqueChocolatier on Instagram for a chance to be featured and receive an exclusive artisanal tasting gift.",
    )


def build_cancellation_template(
    *,
    name: str,
    order_id: str,
    order_total: float,
    cancellation_reason: str = "",
) -> str:
    """Build an order cancellation email."""
    base_url = _get_base_url()
    rows = [
        ("Order Reference", f"#{order_id}"),
        ("Order Total", f"₹{order_total:,.2f}"),
        ("Cancellation Reason", cancellation_reason or "Customer request"),
        ("Refund Status", "Initiated (if payment completed)"),
    ]
    return render_luxury_email(
        subject=f"Order Cancelled – #{order_id}",
        headline="Order Cancellation Confirmation",
        recipient_name=name,
        badge_text="Order Cancelled",
        badge_bg="#FEE2E2",
        badge_color="#DC2626",
        body_paragraphs=[
            f"As requested, order <strong>#{order_id}</strong> has been cancelled.",
            "If your payment was already processed, our finance team has initiated a full refund to your original payment method.",
        ],
        summary_card_rows=rows,
        cta_text="Explore Other Confections",
        cta_url=f"{base_url}/shop",
        tip_note="Refunds usually reflect in your bank account or card within 3-5 business days depending on your bank.",
    )


def build_refund_template(
    *,
    name: str,
    order_id: str,
    amount: float,
    reference: str = "",
    status: str = "Initiated",
) -> str:
    """Build a refund notification email."""
    base_url = _get_base_url()
    rows = [
        ("Order Reference", f"#{order_id}"),
        ("Refund Amount", f"₹{amount:,.2f}"),
        ("Status", status.title()),
        ("Reference ID", reference or f"RFND-{order_id[-6:]}"),
    ]
    return render_luxury_email(
        subject=f"Refund {status.title()} – Order #{order_id}",
        headline="Refund Update for Your Order",
        recipient_name=name,
        badge_text=f"Refund {status.title()}",
        badge_bg="#E8F8F0",
        badge_color="#1B7F45",
        body_paragraphs=[
            f"We have processed a refund of <strong>₹{amount:,.2f}</strong> for order <strong>#{order_id}</strong>.",
            "The amount will be credited back to your original payment method according to your bank's processing cycles.",
        ],
        summary_card_rows=rows,
        cta_text="Check Account Dashboard",
        cta_url=f"{base_url}/dashboard",
    )


def build_coins_template(
    *,
    name: str,
    event_type: str,  # "earned", "used", "restored"
    coins: int,
    balance: int,
    order_id: str = "",
) -> str:
    """Build a reward coins update email."""
    base_url = _get_base_url()
    if event_type == "earned":
        title = "Chovique Reward Coins Added!"
        badge = "🪙 Coins Credited"
        msg = f"Congratulations! You just earned <strong>{coins} Royal Chovique Coins</strong>."
    elif event_type == "used":
        title = "Chovique Reward Coins Redeemed"
        badge = "🪙 Coins Redeemed"
        msg = f"You redeemed <strong>{coins} Royal Chovique Coins</strong> on order #{order_id}."
    else:
        title = "Chovique Reward Coins Restored"
        badge = "🪙 Coins Restored"
        msg = f"<strong>{coins} Royal Chovique Coins</strong> have been restored to your balance."

    rows = [
        ("Coins Transaction", f"{'+' if event_type != 'used' else '-'}{coins} Coins"),
        ("New Coins Balance", f"{balance} Coins"),
        ("Redeemable Value", f"₹{balance * 1.0:,.2f}"),
    ]

    return render_luxury_email(
        subject=title,
        headline=title,
        recipient_name=name,
        badge_text=badge,
        badge_bg="#FFF8E1",
        badge_color="#B78103",
        body_paragraphs=[
            msg,
            "You can apply your Royal Chovique Coins during checkout to unlock complimentary tastings and exclusive price privileges.",
        ],
        summary_card_rows=rows,
        cta_text="Redeem in Boutique",
        cta_url=f"{base_url}/shop",
    )


def build_ticket_template(
    *,
    name: str,
    ticket_id: str,
    subject_text: str,
    status: str,
    message: str,
    is_update: bool = False,
) -> str:
    """Build support ticket acknowledgment or reply email."""
    base_url = _get_base_url()
    rows = [
        ("Ticket ID", f"#{ticket_id}"),
        ("Subject", subject_text),
        ("Status", status.title()),
    ]
    headline = "Support Ticket Update" if is_update else "Support Request Received"
    return render_luxury_email(
        subject=f"[{headline}] #{ticket_id} – {subject_text}",
        headline=headline,
        recipient_name=name,
        badge_text=f"Ticket {status.title()}",
        badge_bg="#F3F4F6",
        badge_color="#374151",
        body_paragraphs=[
            f"Here is an update on your support request <strong>#{ticket_id}</strong>:",
            f'<div style="background-color: #FAF7F2; border-left: 3px solid #D4AF37; padding: 12px 16px; border-radius: 4px; margin: 12px 0; color: #2D2421; font-style: italic;">{message}</div>',
        ],
        summary_card_rows=rows,
        cta_text="View Ticket in Dashboard",
        cta_url=f"{base_url}/dashboard",
    )


def build_generic_notification_template(
    *,
    subject: str,
    headline: str,
    recipient_name: str,
    body_paragraphs: List[str],
    key_values: Optional[List[Tuple[str, str]]] = None,
    badge_text: Optional[str] = None,
    cta_text: Optional[str] = None,
    cta_url: Optional[str] = None,
) -> str:
    """Universal luxury wrapper for any notification (superadmin, admin, or user)."""
    return render_luxury_email(
        subject=subject,
        headline=headline,
        recipient_name=recipient_name,
        badge_text=badge_text or "Platform Notification",
        badge_bg="#FAF7F2",
        badge_color="#6B5E57",
        body_paragraphs=body_paragraphs,
        summary_card_rows=key_values,
        cta_text=cta_text,
        cta_url=cta_url,
    )
