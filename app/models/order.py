import uuid
import random
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


import secrets

def generate_order_id():
    return f"ORD-{secrets.randbelow(90000) + 10000}-{str(uuid.uuid4())[:4].upper()}"


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=generate_order_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    total = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)
    discount = Column(Float, default=0.0, nullable=False)
    coupon_code = Column(String(50), nullable=True)
    coupon_discount = Column(Float, default=0.0, nullable=False)
    coins_used = Column(Integer, default=0, nullable=False)
    coin_discount = Column(Float, default=0.0, nullable=False)
    coins_earned = Column(Integer, default=0, nullable=False)
    shipping = Column(Float, default=0.0, nullable=False)
    tax = Column(Float, default=0.0, nullable=False)
    status = Column(String(50), default="Processing", nullable=False, index=True)
    payment_status = Column(String(50), default="PENDING", nullable=False, index=True)
    shipping_address = Column(JSON, nullable=False)
    delivery_option = Column(String(100), default="Standard Delivery", nullable=False)
    payment_method = Column(String(100), default="UPI", nullable=False)
    invoice_url = Column(String(500), nullable=True)

    # ─── Dual-Mode Fulfillment & Store Origin Snapshot ────────────────
    store_location_id = Column(String(36), ForeignKey("store_locations.id", ondelete="SET NULL"), nullable=True, index=True)
    fulfillment_type = Column(String(50), default="LOCAL", nullable=False, index=True)  # LOCAL, COURIER
    shipping_provider = Column(String(50), default="INTERNAL", nullable=False)  # INTERNAL, SHIPROCKET, DELHIVERY, OTHER
    fulfillment_status = Column(String(50), default="UNASSIGNED", nullable=False, index=True)  # UNASSIGNED, ASSIGNED, PICKED_UP, OUT_FOR_DELIVERY, DELIVERED, FAILED
    delivery_boy_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # ─── Authoritative Immutable Shipping Snapshot ───────────────────
    shipping_name = Column(String(120), nullable=True)
    shipping_phone = Column(String(30), nullable=True)
    shipping_house_number = Column(String(100), nullable=True)
    shipping_street = Column(String(255), nullable=True)
    shipping_area = Column(String(150), nullable=True)
    shipping_landmark = Column(String(150), nullable=True)
    shipping_city = Column(String(100), nullable=True)
    shipping_district = Column(String(100), nullable=True)
    shipping_state = Column(String(100), nullable=True)
    shipping_pincode = Column(String(20), nullable=True, index=True)
    shipping_latitude = Column(Float, nullable=True)
    shipping_longitude = Column(Float, nullable=True)
    shipping_formatted_address = Column(String(500), nullable=True)
    shipping_google_place_id = Column(String(255), nullable=True)
    shipping_location_source = Column(String(50), nullable=True)
    shipping_location_verified = Column(Boolean, default=False, nullable=True)
    shipping_delivery_charge = Column(Float, nullable=True)
    shipping_confirmed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    paid_at = Column(DateTime(timezone=True), nullable=True, index=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    returned_at = Column(DateTime(timezone=True), nullable=True)
    return_reason = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # ─── Delivery Boy Workflow ────────────────────────────────────
    delivery_otp = Column(String(6), nullable=True)
    delivery_otp_expires_at = Column(DateTime(timezone=True), nullable=True)
    delivery_accepted_at = Column(DateTime(timezone=True), nullable=True)
    delivery_rejected_at = Column(DateTime(timezone=True), nullable=True)
    delivery_rejection_reason = Column(Text, nullable=True)
    delivery_picked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    delivery_boy = relationship("User", foreign_keys=[delivery_boy_id], lazy="selectin")
    store_location = relationship("StoreLocation", foreign_keys=[store_location_id], lazy="selectin")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(String(36), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    quantity = Column(Integer, default=1, nullable=False)
    price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", lazy="selectin")


class OrderSequence(Base):
    __tablename__ = "order_sequences"

    id = Column(Integer, primary_key=True, default=1)
    current_seq = Column(Integer, nullable=False, default=0)

