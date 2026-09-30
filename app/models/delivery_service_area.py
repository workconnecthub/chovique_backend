import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class DeliveryServiceArea(Base):
    __tablename__ = "delivery_service_areas"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    store_location_id = Column(String(36), ForeignKey("store_locations.id", ondelete="SET NULL"), nullable=True, index=True)
    pincode = Column(String(10), unique=True, nullable=False, index=True)
    city = Column(String(100), nullable=False, default="Visakhapatnam")
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=False, default="Andhra Pradesh")
    delivery_mode = Column(String(50), nullable=False, default="LOCAL")  # LOCAL, COURIER, UNAVAILABLE
    delivery_charge = Column(Float, nullable=False, default=40.0)
    free_delivery_threshold = Column(Float, nullable=True)  # If order subtotal >= threshold, charge = 0. Null means no threshold override
    same_day_available = Column(Boolean, nullable=False, default=True)
    estimated_delivery = Column(String(100), nullable=False, default="Within 3-5 hours (Same Day)")
    active = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    store_location = relationship("StoreLocation", lazy="selectin")
