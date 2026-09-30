import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, String
from sqlalchemy.sql import func
from app.db.base import Base


class StoreLocation(Base):
    __tablename__ = "store_locations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(120), nullable=False)
    house_number = Column(String(100), nullable=True)
    street = Column(String(255), nullable=False)
    area = Column(String(150), nullable=True)
    city = Column(String(100), nullable=False, default="Visakhapatnam")
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=False, default="Andhra Pradesh")
    pincode = Column(String(10), nullable=False, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    formatted_address = Column(String(500), nullable=True)
    google_place_id = Column(String(255), nullable=True)
    phone = Column(String(30), nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
