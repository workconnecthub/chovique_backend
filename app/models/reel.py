import uuid
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func
from app.db.base import Base


class InstagramReel(Base):
    __tablename__ = "instagram_reels"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    video_url = Column(String(500), nullable=True)
    instagram_url = Column(String(500), nullable=True)
    account_name = Column(String(100), default="@chovique_chocolatier", nullable=True)
    likes = Column(String(20), default="0", nullable=True)
    comments = Column(String(20), default="0", nullable=True)
    views = Column(String(20), default="0 views", nullable=True)
    title = Column(String(255), default="Instagram Reel", nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
