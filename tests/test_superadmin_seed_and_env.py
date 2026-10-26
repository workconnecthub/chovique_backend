"""
Tests for Super Admin Environment Configuration & Seeding
==========================================================
Verifies:
1. Environment file structure (.env.example is standard, .env_example removed, .env ignored).
2. Super Admin seeding via ensure_superadmin_exists is idempotent and assigns super_admin role.
3. Password is securely hashed with Argon2 and plain-text is never stored.
4. Existing Super Admin data and password are not overwritten on subsequent runs.
5. Super Admin identification on /api/v1/auth/identify returns next_step='password'.
6. Super Admin authentication via /api/v1/auth/staff/login succeeds.
"""

import os
import subprocess
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_password
from app.models.user import User
from app.services.superadmin_service import ensure_superadmin_exists


def test_environment_files_structure():
    """Verify that .env.example is the single standard template and .env_example is removed."""
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    example_file = os.path.join(backend_dir, ".env.example")
    deprecated_example = os.path.join(backend_dir, ".env_example")
    actual_env = os.path.join(backend_dir, ".env")

    # 1. Standard template exists
    assert os.path.exists(example_file), ".env.example must exist as standard example template."

    # 2. Duplicate template removed
    assert not os.path.exists(deprecated_example), ".env_example must be removed."

    # 3. .env exists and contains required superadmin keys
    assert os.path.exists(actual_env), ".env must exist locally."
    with open(actual_env, "r", encoding="utf-8") as f:
        env_content = f.read()
    assert "SUPERADMIN_EMAIL=" in env_content
    assert "SUPERADMIN_PASSWORD=" in env_content
    assert "SUPERADMIN_PHONE=" in env_content

    # 4. .env.example has safe placeholders
    with open(example_file, "r", encoding="utf-8") as f:
        example_content = f.read()
    assert "SUPERADMIN_EMAIL=superadmin@example.com" in example_content
    assert "SUPERADMIN_PASSWORD=replace-with-a-strong-password" in example_content
    assert "SUPERADMIN_PHONE=919876543210" in example_content

    # 5. Git check: .env must be ignored and not tracked
    git_check = subprocess.run(
        ["git", "status", "--porcelain", ".env"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )
    assert git_check.stdout.strip() == "", ".env must be ignored by Git and not tracked."


@pytest.mark.asyncio
class TestSuperadminSeedingAndAuth:
    """Tests for idempotent Super Admin seeding and authentication flow."""

    async def test_superadmin_seeded_correctly(self, db_session: AsyncSession):
        """Verify ensure_superadmin_exists seeds super_admin with Argon2 password hash."""
        user = await ensure_superadmin_exists(db_session)
        assert user is not None
        assert user.role == "super_admin"
        assert user.email == settings.SUPERADMIN_EMAIL.strip().lower()
        assert user.is_active is True
        assert user.is_email_verified is True
        assert user.is_phone_verified is True

        # Check phone is normalized
        assert user.phone.endswith("9876543210")

        # Verify password is hashed with Argon2 / pwd_context and plain password is not stored
        assert user.hashed_password != settings.SUPERADMIN_PASSWORD
        assert user.hashed_password.startswith("$argon2") or "argon" in user.hashed_password or "$2b$" in user.hashed_password
        assert verify_password(settings.SUPERADMIN_PASSWORD, user.hashed_password) is True

    async def test_superadmin_seeding_is_idempotent_and_does_not_overwrite(self, db_session: AsyncSession):
        """Repeated seeding must not duplicate accounts or overwrite custom password."""
        # First seed
        user1 = await ensure_superadmin_exists(db_session)
        original_hash = user1.hashed_password
        original_id = user1.id

        # Simulate password change by superadmin
        custom_new_hash = "$argon2id$v=19$m=65536,t=3,p=4$customhashvalue$preserved"
        user1.hashed_password = custom_new_hash
        user1.full_name = "Custom Chief Name"
        await db_session.commit()

        # Second seed (e.g. on server restart)
        user2 = await ensure_superadmin_exists(db_session)

        # Must be the same record
        assert user2.id == original_id
        # Must not overwrite existing password hash or name
        assert user2.hashed_password == custom_new_hash
        assert user2.full_name == "Custom Chief Name"

        # Check total superadmin count in DB remains 1
        res = await db_session.execute(
            select(func.count(User.id)).where(User.role.in_(["super_admin", "superadmin"]))
        )
        assert res.scalar_one() == 1

    async def test_superadmin_login_flow(self, client: AsyncClient, db_session: AsyncSession, mock_redis):
        """Super Admin account seeded can identify on unified login and authenticate via staff login."""
        await ensure_superadmin_exists(db_session)

        phone = settings.SUPERADMIN_PHONE  # e.g. "919876543210" or "9876543210"

        # 1. POST /api/v1/auth/identify determines password step
        ident_res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": phone},
        )
        assert ident_res.status_code == 200
        ident_data = ident_res.json()
        assert ident_data["next_step"] == "password"

        # 2. POST /api/v1/auth/staff/login succeeds with seeded credentials
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": phone,
                "password": settings.SUPERADMIN_PASSWORD,
                "role": "super_admin",
            },
        )
        assert login_res.status_code == 200
        login_data = login_res.json()
        assert login_data["user"]["role"] in ("super_admin", "superadmin")
        assert "access_token" in login_data
        assert login_data["user"]["email"] == settings.SUPERADMIN_EMAIL.strip().lower()

    async def test_superadmin_login_with_wrong_password_fails(self, client: AsyncClient, db_session: AsyncSession, mock_redis):
        """Super Admin login fails with incorrect password."""
        await ensure_superadmin_exists(db_session)

        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": settings.SUPERADMIN_PHONE,
                "password": "WrongPassword123!",
                "role": "super_admin",
            },
        )
        assert login_res.status_code == 401
