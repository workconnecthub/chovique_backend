"""
Pytest configuration and fixtures for async testing.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
import app.models  # Ensure all models are registered with Base.metadata
from app.db.session import get_db
from app.main import app


# ==========================================================
# Event Loop
# ==========================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ==========================================================
# ==========================================================
# Test Database Engine (PostgreSQL isolated test DB)
# ==========================================================

import os
from sqlalchemy import text
from sqlalchemy.pool import NullPool

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:chukki12@localhost:5433/chovique_test_db",
)

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    poolclass=NullPool,
    echo=False,
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


# ==========================================================
# Database Setup / Teardown
# ==========================================================

@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    """Create tables before each test and clean table data between tests."""
    async with test_engine.connect() as conn:
        autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        for val in ["delivery_boy", "delivery_person", "super_admin"]:
            try:
                await autocommit_conn.execute(text(f"ALTER TYPE user_role ADD VALUE IF NOT EXISTS '{val}';"))
            except Exception:
                pass

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for stmt in [
            "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500);",
            "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS return_request_id VARCHAR(36);",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_requests_enabled BOOLEAN NOT NULL DEFAULT TRUE;",
            "ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_window_value INTEGER NOT NULL DEFAULT 30;",
            "ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_window_unit VARCHAR(20) NOT NULL DEFAULT 'minutes';",
            "ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_photo_required BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS assigned_admin VARCHAR(120);",
            "ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception as e:
                print(f"Warning running {stmt}: {e}")

    yield


    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            try:
                await conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE;'))
            except Exception:
                pass


# ==========================================================
# Override get_db dependency
# ==========================================================

async def override_get_db():
    async with TestSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_db] = override_get_db


# ==========================================================
# Mock Redis (using fakeredis)
# ==========================================================

@pytest.fixture(autouse=True)
def mock_redis():
    """Replace the real Redis client with fakeredis for all tests."""
    import fakeredis.aioredis

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    with patch("app.services.otp_service.redis_client", fake_redis):
        with patch("app.db.redis.redis_client", fake_redis):
            with patch("app.api.deps.redis_client", fake_redis):
                with patch("app.middleware.rate_limit_middleware.redis_client", fake_redis):
                    yield fake_redis


# ==========================================================
# Mock Mail Service
# ==========================================================

@pytest.fixture(autouse=True)
def mock_mail():
    """Prevent actual emails from being sent during tests."""
    with patch(
        "app.services.mail_service.MailService.send_registration_otp",
        new_callable=AsyncMock,
    ) as mock_reg:
        with patch(
            "app.services.mail_service.MailService.send_forgot_password_otp",
            new_callable=AsyncMock,
        ) as mock_forgot:
            yield {"registration": mock_reg, "forgot": mock_forgot}


# ==========================================================
# Async HTTP Client
# ==========================================================

@pytest_asyncio.fixture
async def client():
    """Async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac


# ==========================================================
# Test DB Session
# ==========================================================

@pytest_asyncio.fixture
async def db_session():
    """Provide a test database session."""
    async with TestSessionLocal() as session:
        yield session


# ==========================================================
# Helper: Register + Verify a test user
# ==========================================================

@pytest_asyncio.fixture
async def authenticated_client(client: AsyncClient, mock_redis):
    """
    Returns an AsyncClient with auth cookies and Bearer headers set
    for a test customer user.
    """
    import secrets
    from app.models.user import User
    from app.core.security import hash_password, create_access_token

    csrf_token = secrets.token_hex(16)
    async with TestSessionLocal() as session:
        user = User(
            email="test@example.com",
            full_name="Test User",
            phone="919999999999",
            role="customer",
            hashed_password=hash_password("TestPass123!"),
            is_email_verified=True,
            is_phone_verified=True,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = str(user.id)

    access_token = create_access_token(user_id)
    client.cookies.set("access_token", access_token)
    client.cookies.set("csrf_token", csrf_token)
    client.headers["Authorization"] = f"Bearer {access_token}"
    client.headers["x-csrf-token"] = csrf_token
    setattr(client, "user_id", user_id)
    yield client

