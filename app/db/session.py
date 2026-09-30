"""
Database session configuration.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.db.base import Base

# Import all models so they are registered with SQLAlchemy metadata
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.product import Product  # noqa: F401
from app.models.banner import Banner  # noqa: F401
from app.models.testimonial import Testimonial  # noqa: F401
from app.models.site_config import SiteConfig  # noqa: F401
from app.models.address import CustomerAddress  # noqa: F401
from app.models.coupon import Coupon  # noqa: F401
from app.models.order import Order, OrderItem, OrderSequence  # noqa: F401
from app.models.ticket import SupportTicket  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.contact import ContactMessage  # noqa: F401
from app.models.review import ProductReview  # noqa: F401
from app.models.reel import InstagramReel  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.cart import Cart, CartItem  # noqa: F401
from app.models.wishlist import WishlistItem  # noqa: F401
from app.models.payment import Payment  # noqa: F401
from app.models.refund import Refund  # noqa: F401
from app.models.faq import FAQ  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.offline_sale import OfflineSale  # noqa: F401
from app.models.theme import ThemePreset  # noqa: F401
from app.models.wallet import UserWallet, CoinTransaction  # noqa: F401
from app.models.store_location import StoreLocation  # noqa: F401
from app.models.delivery_service_area import DeliveryServiceArea  # noqa: F401
# ==========================================================
# Create Async Engine
# ==========================================================

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO,
    future=True,
    pool_pre_ping=True,
)

# ==========================================================
# Session Factory
# ==========================================================

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)

# ==========================================================
# Database Initialization
# ==========================================================


from sqlalchemy import text


async def init_db() -> None:
    """
    Create database tables if they do not already exist and run schema migrations.
    """

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        alter_statements = [
            # Products
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS sku VARCHAR(50);",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS stock INTEGER NOT NULL DEFAULT 100;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_featured BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_bestseller BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_new_arrival BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS images JSON;",
            # Orders
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) NOT NULL DEFAULT 'PENDING';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;",
            "UPDATE orders SET paid_at = created_at WHERE UPPER(payment_status) = 'PAID' AND paid_at IS NULL;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS invoice_url VARCHAR(500);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS tax DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS coupon_code VARCHAR(50);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS coupon_discount DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS coins_used INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS coin_discount DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS coins_earned INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_option VARCHAR(100) NOT NULL DEFAULT 'Standard Delivery';",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(100) NOT NULL DEFAULT 'UPI';",
            # Product Reviews
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'approved';",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS title VARCHAR(200);",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS images JSON;",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS videos JSON;",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS is_verified_purchase BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE product_reviews ADD COLUMN IF NOT EXISTS is_featured_on_home BOOLEAN NOT NULL DEFAULT FALSE;",
            # Categories
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;",
            "ALTER TABLE categories ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;",
            # Testimonials
            "ALTER TABLE testimonials ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);",
            "ALTER TABLE testimonials ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'approved';",
            "ALTER TABLE testimonials ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP;",
            # Notifications
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS admin_id VARCHAR(36);",
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS title VARCHAR(200);",
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS message TEXT;",
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_type VARCHAR(50);",
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS related_entity_id VARCHAR(50);",
            "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS is_read BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE notifications ALTER COLUMN user_id DROP NOT NULL;",
            "ALTER TABLE notifications ALTER COLUMN text DROP NOT NULL;",
            # Users
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT;",
            # Offline Sales
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS receipt_id VARCHAR(100);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS company_name VARCHAR(255) DEFAULT 'Direct Customer';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS contact_person VARCHAR(255) DEFAULT 'Walk-in';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS phone VARCHAR(50) DEFAULT 'N/A';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS email VARCHAR(255);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS address TEXT DEFAULT 'N/A';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS payment_method VARCHAR(100) NOT NULL DEFAULT 'Cash';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS subtotal DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS discount DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS tax DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS total_amount DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'Completed';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS payment_status VARCHAR(50) NOT NULL DEFAULT 'Paid';",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS received_amount DOUBLE PRECISION;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS receipt_number VARCHAR(100);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS card_type VARCHAR(50);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS card_last4 VARCHAR(4);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS transaction_id VARCHAR(100);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS upi_id VARCHAR(100);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS bank_name VARCHAR(100);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS account_holder VARCHAR(255);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS product_name VARCHAR(255);",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;",
            "ALTER TABLE offline_sales ADD COLUMN IF NOT EXISTS total_price DOUBLE PRECISION DEFAULT 0.0;",
            "UPDATE offline_sales SET receipt_id = 'OFF-' || UPPER(SUBSTRING(id FROM 1 FOR 8)) WHERE receipt_id IS NULL;",
            # Products rating backfill
            "UPDATE products SET rating = 4.8 WHERE (name ILIKE '%Royal Truffle%' OR name ILIKE '%Royal%') AND (rating IS NULL OR rating = 0.0);",
            "UPDATE products SET rating = 4.5 WHERE (name ILIKE '%Belgian Dark%' OR name ILIKE '%Belgian%') AND (rating IS NULL OR rating = 0.0);",
            "UPDATE products SET rating = 4.9 WHERE (name ILIKE '%Gold Leaf%' OR name ILIKE '%Pralines%') AND (rating IS NULL OR rating = 0.0);",
            "UPDATE products SET rating = 4.7 WHERE (name ILIKE '%Hazelnut%' OR name ILIKE '%Crunch%') AND (rating IS NULL OR rating = 0.0);",
            "UPDATE products SET rating = 4.8 WHERE (name ILIKE '%Salted Caramel%' OR name ILIKE '%Bonbons%') AND (rating IS NULL OR rating = 0.0);",
            "UPDATE products SET rating = 4.6 WHERE (name ILIKE '%White Macadamia%' OR name ILIKE '%Macadamia%') AND (rating IS NULL OR rating = 0.0);",
            # Cleanup removed Inventory module table
            "DROP TABLE IF EXISTS inventory_logs CASCADE;",
            # Instagram Reels enhancements
            "ALTER TABLE instagram_reels ADD COLUMN IF NOT EXISTS instagram_url VARCHAR(500);",
            "ALTER TABLE instagram_reels ADD COLUMN IF NOT EXISTS account_name VARCHAR(100) DEFAULT '@chovique_chocolatier';",
            "ALTER TABLE instagram_reels ALTER COLUMN video_url DROP NOT NULL;",
            "ALTER TABLE instagram_reels ALTER COLUMN title DROP NOT NULL;",
            "ALTER TABLE instagram_reels ALTER COLUMN likes DROP NOT NULL;",
            "ALTER TABLE instagram_reels ALTER COLUMN comments DROP NOT NULL;",
            "ALTER TABLE instagram_reels ALTER COLUMN views DROP NOT NULL;",
        ]
        for stmt in alter_statements:
            try:
                await connection.execute(text(stmt))
            except Exception:
                pass



# ==========================================================
# Dependency
# ==========================================================


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session.
    """

    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
