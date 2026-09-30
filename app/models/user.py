import uuid

from sqlalchemy import Boolean, Column, Date, DateTime, Enum, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    # ==========================
    # Primary Key
    # ==========================
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # ==========================
    # Authentication
    # ==========================
    full_name = Column(String(120), nullable=False)
    email = Column(String(254), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=True)
    google_id = Column(String(120), unique=True, nullable=True)

    role = Column(
        Enum("customer", "admin", "superadmin", "delivery_boy", name="user_role"),
        nullable=False,
        default="customer",
    )

    # ==========================
    # Profile
    # ==========================
    phone = Column(String(20), nullable=True)
    address = Column(Text, nullable=True)
    dob = Column(Date, nullable=True)
    gender = Column(String(20), nullable=True)
    avatar_url = Column(Text, nullable=True)

    # ==========================
    # Status
    # ==========================
    is_email_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # ==========================
    # Audit
    # ==========================
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ==========================
    # Relationships
    # ==========================
    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    addresses = relationship(
        "CustomerAddress",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    cart = relationship(
        "Cart",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="selectin",
    )