import uuid
import random
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, Integer
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


import secrets

def generate_ticket_id():
    return f"TKT-{secrets.randbelow(9000) + 1000}"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id = Column(String(36), primary_key=True, default=generate_ticket_id)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_name = Column(String(120), nullable=False)
    category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    order_id = Column(String(36), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), default="Pending", nullable=False, index=True)
    status_change_count = Column(Integer, default=0, nullable=False)
    admin_notes = Column(Text, nullable=True)
    customer_resolution_feedback = Column(String(50), nullable=True)
    notified = Column(Boolean, default=False, nullable=False)
    photo_url = Column(String(500), nullable=True)
    return_request_id = Column(String(36), nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    assigned_admin = Column(String(120), nullable=True)

    customer = relationship("User")
    order = relationship("Order")
