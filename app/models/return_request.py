import secrets
from sqlalchemy import Column, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


def generate_return_id() -> str:
    """Generate a clean return request ID, e.g. RET-58291."""
    return f"RET-{secrets.randbelow(90000) + 10000}"


class ReturnRequest(Base):
    __tablename__ = "return_requests"

    id = Column(String(36), primary_key=True, default=generate_return_id)
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    ticket_id = Column(String(36), ForeignKey("support_tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_name = Column(String(120), nullable=False)
    customer_email = Column(String(255), nullable=True)
    customer_phone = Column(String(50), nullable=True)
    order_amount = Column(Float, nullable=False)
    payment_method = Column(String(100), nullable=False)
    delivery_address = Column(JSON, nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=False)
    reason = Column(String(100), nullable=False)  # One of the 6 standard reasons
    description = Column(Text, nullable=False)
    photo_url = Column(String(500), nullable=True)
    status = Column(String(50), default="Pending", nullable=False, index=True)  # Pending, Under Review, Approved, Rejected, Resolved
    admin_notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # Relationships
    order = relationship("Order", lazy="selectin")
    customer = relationship("User", foreign_keys=[customer_id], lazy="selectin")
    ticket = relationship("SupportTicket", foreign_keys=[ticket_id], lazy="selectin")
