import uuid
from sqlalchemy import Column, String, Boolean, DateTime, Float, Integer, Text, ForeignKey
from sqlalchemy.sql import func
from app.db.base import Base


class PlatformSettings(Base):
    """
    Single-row table that stores all global platform configuration for Chovique.
    There is always exactly one row (id = 'singleton').
    """
    __tablename__ = "platform_settings"

    id = Column(String(36), primary_key=True, default="singleton")

    # ── Store Configuration ────────────────────────────────────────────────
    store_front_name = Column(String(200), nullable=False, default="Chovique Luxury Chocolates")
    support_email = Column(String(255), nullable=False, default="support@chovique.com")
    support_phone = Column(String(30), nullable=False, default="+91 83098 54870")
    store_address = Column(Text, nullable=True, default="")
    city = Column(String(100), nullable=True, default="")
    state = Column(String(100), nullable=True, default="")
    country = Column(String(100), nullable=False, default="India")
    pincode = Column(String(20), nullable=True, default="")
    base_currency = Column(String(10), nullable=False, default="INR")
    timezone = Column(String(60), nullable=False, default="Asia/Kolkata")
    business_status = Column(String(20), nullable=False, default="active")  # active | paused | closed

    # ── Payment & Shipping ─────────────────────────────────────────────────
    cod_enabled = Column(Boolean, nullable=False, default=True)
    gst_rate = Column(Float, nullable=False, default=18.0)           # 0–100 %
    platform_fee = Column(Float, nullable=False, default=0.0)        # ₹
    standard_shipping_charge = Column(Float, nullable=False, default=50.0)
    free_shipping_min_order = Column(Float, nullable=False, default=500.0)
    maximum_cod_order_value = Column(Float, nullable=False, default=5000.0)

    # ── Customer & Order Settings ──────────────────────────────────────────
    customer_registration_enabled = Column(Boolean, nullable=False, default=True)
    guest_checkout_enabled = Column(Boolean, nullable=False, default=True)
    minimum_order_value = Column(Float, nullable=False, default=100.0)
    order_cancellation_enabled = Column(Boolean, nullable=False, default=True)
    cancellation_time_limit = Column(Integer, nullable=False, default=24)    # hours
    return_refund_enabled = Column(Boolean, nullable=False, default=True)
    return_requests_enabled = Column(Boolean, nullable=False, default=True)
    return_window_value = Column(Integer, nullable=False, default=30)
    return_window_unit = Column(String(20), nullable=False, default="minutes")  # minutes | hours | days
    return_photo_required = Column(Boolean, nullable=False, default=False)

    # ── System & Security ──────────────────────────────────────────────────
    maintenance_mode = Column(Boolean, nullable=False, default=False)
    admin_session_timeout = Column(Integer, nullable=False, default=60)      # minutes
    max_login_attempts = Column(Integer, nullable=False, default=5)
    account_lockout_duration = Column(Integer, nullable=False, default=30)   # minutes

    # ── Audit ──────────────────────────────────────────────────────────────
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    updated_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
