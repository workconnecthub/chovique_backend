import uuid
from sqlalchemy import Column, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class DeliveryPersonLocation(Base):
    """
    Stores the current (latest) location of each delivery person.
    One row per delivery person — upserted on every location update.
    Historical tracking is intentionally omitted to keep the table lean;
    only the most-recent position is needed for route optimisation.
    """

    __tablename__ = "delivery_person_locations"

    delivery_person_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=True)   # metres (from browser Geolocation API)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    delivery_person = relationship("User", foreign_keys=[delivery_person_id])
