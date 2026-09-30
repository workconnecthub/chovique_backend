import uuid
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base


class ProductReview(Base):
    __tablename__ = "product_reviews"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author = Column(String(120), nullable=False)
    rating = Column(Float, nullable=False, default=5.0)
    text = Column(Text, nullable=False)
    avatar = Column(String(10), nullable=True)
    status = Column(String(20), default="approved", nullable=False, index=True)

    title = Column(String(200), nullable=True)
    images = Column(JSON, nullable=True, default=list)
    videos = Column(JSON, nullable=True, default=list)
    is_verified_purchase = Column(Boolean, default=False, nullable=False)
    is_featured_on_home = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    product = relationship("Product", backref="reviews_list")
