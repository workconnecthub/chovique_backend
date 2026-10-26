import uuid
from sqlalchemy import Column, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.sql import func
from app.db.base import Base


class OTPDailyLimit(Base):
    __tablename__ = "otp_daily_limits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    identifier = Column(String(100), nullable=False, index=True)
    send_date = Column(Date, nullable=False, default=func.current_date(), index=True)
    send_count = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("identifier", "send_date", name="uq_otp_daily_limit_identifier_date"),
    )
