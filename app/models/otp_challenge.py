import uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func
from app.db.base import Base


class OTPChallenge(Base):
    __tablename__ = "otp_challenges"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    identifier = Column(String(100), nullable=False, index=True)
    purpose = Column(String(50), nullable=False, default="customer_login")
    hashed_otp = Column(String(255), nullable=False)
    salt = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    resend_count = Column(Integer, nullable=False, default=0)
    last_sent_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_consumed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
