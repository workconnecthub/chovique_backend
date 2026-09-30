import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(50), nullable=False, default="Home")
    name = Column(String(120), nullable=False)
    house_number = Column(String(100), nullable=True)
    street = Column(String(255), nullable=False)
    area = Column(String(150), nullable=True)
    landmark = Column(String(150), nullable=True)
    city = Column(String(100), nullable=False)
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=False)
    zip = Column(String(20), nullable=False)
    phone = Column(String(30), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    formatted_address = Column(String(500), nullable=True)
    google_place_id = Column(String(255), nullable=True)
    location_source = Column(String(50), default="MANUAL", nullable=False)  # GOOGLE_PLACE, CURRENT_LOCATION, MANUAL, SAVED_ADDRESS
    location_verified = Column(Boolean, default=False, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    user = relationship("User", back_populates="addresses")

