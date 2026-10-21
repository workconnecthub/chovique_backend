import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    JSON,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    # ==========================
    # Primary Key
    # ==========================
    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # ==========================
    # Core Fields
    # ==========================
    name = Column(String(200), nullable=False, index=True)
    slug = Column(String(220), unique=True, nullable=False, index=True)
    category_id = Column(
        String(36),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    category_rel = relationship("Category", backref="products", lazy="joined")

    @property
    def category(self) -> str:
        if self.category_rel:
            return self.category_rel.name
        return ""
    price = Column(Float, nullable=False)
    original_price = Column(Float, nullable=True)
    weight = Column(String(50), nullable=True)
    stock = Column(Integer, default=100, nullable=False, index=True)
    sku = Column(String(50), nullable=True, index=True)

    # ==========================
    # Details
    # ==========================
    description = Column(Text, nullable=True)
    ingredients = Column(Text, nullable=True)
    # ==========================
    # Display
    # ==========================
    badge = Column(
        String(50),
        nullable=True,
    )


    image = Column(Text, nullable=True)
    hover_image = Column(Text, nullable=True)
    images = Column(JSON, nullable=True, default=list)

    # ==========================
    # Ratings
    # ==========================
    rating = Column(Float, default=0.0, nullable=False)
    ratings_count = Column(Integer, default=0, nullable=False)

    # ==========================
    # Management & Flags
    # ==========================
    is_available = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_featured = Column(Boolean, default=False, nullable=False)
    is_bestseller = Column(Boolean, default=False, nullable=False)
    is_new_arrival = Column(Boolean, default=False, nullable=False)
    is_sample = Column(Boolean, default=False, nullable=False)
    sample_price = Column(Float, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)

    # ==========================
    # Audit
    # ==========================
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
