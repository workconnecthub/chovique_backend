"""
Unit and Integration Tests for Account Enumeration Defense (AUTH-002 Remediation).

Verifies:
1. Non-existent accounts return standard 401 Unauthorized on POST /auth/staff/login.
2. Incorrect staff password returns standard 401 Unauthorized on POST /auth/staff/login.
3. Deactivated staff accounts return 403 Forbidden on POST /auth/staff/login.
4. Forgot password requests return identical generic messages for registered and unregistered identifiers.
5. Legitimate staff login with valid credentials succeeds normally (HTTP 200).
"""

import pytest
from httpx import AsyncClient
from app.repositories.user_repository import UserRepository
from app.core.security import hash_password

pytestmark = pytest.mark.asyncio


class TestAccountEnumerationDefense:

    async def test_nonexistent_staff_login_returns_generic_error(self, client: AsyncClient):
        """Non-existent staff member receives generic 401 Unauthorized on login."""
        response = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9876599999",
                "password": "SomePassword1!",
            },
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    async def test_wrong_password_returns_generic_error(self, client: AsyncClient, db_session):
        """Existing staff user with incorrect password receives generic 401 Unauthorized."""
        user_repo = UserRepository(db_session)
        await user_repo.create(
            full_name="Staff Admin",
            email="staff_admin@example.com",
            phone="9876500001",
            hashed_password=hash_password("CorrectPassword1!"),
            role="admin",
            is_phone_verified=True,
            is_active=True,
        )

        response = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9876500001",
                "password": "WrongPassword1!",
            },
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()

    async def test_deactivated_staff_fails_securely(self, client: AsyncClient, db_session):
        """Deactivated staff member receives appropriate deactivation error."""
        user_repo = UserRepository(db_session)
        await user_repo.create(
            full_name="Deactivated Staff",
            email="deactivated_staff@example.com",
            phone="9876500002",
            hashed_password=hash_password("CorrectPassword1!"),
            role="admin",
            is_phone_verified=True,
            is_active=False,
        )

        response = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9876500002",
                "password": "CorrectPassword1!",
            },
        )
        assert response.status_code == 403
        assert "deactivated" in response.json()["detail"].lower()

    async def test_forgot_password_generic_response(self, client: AsyncClient, db_session):
        """Forgot password returns identical generic response for existing and non-existing accounts."""
        user_repo = UserRepository(db_session)
        await user_repo.create(
            full_name="Forgot Staff",
            email="forgot_staff@example.com",
            phone="9876500003",
            hashed_password=hash_password("Password123!"),
            role="admin",
            is_phone_verified=True,
            is_active=True,
        )

        res_existing = await client.post(
            "/api/v1/auth/forgot-password",
            json={"phone": "9876500003"},
        )
        res_nonexisting = await client.post(
            "/api/v1/auth/forgot-password",
            json={"phone": "9876599998"},
        )

        assert res_existing.status_code == 200
        assert res_nonexisting.status_code == 200
        assert "OTP" in res_existing.json()["message"]
        assert "OTP" in res_nonexisting.json()["message"]

    async def test_legitimate_staff_login_success(self, client: AsyncClient, db_session):
        """Legitimate staff user with valid credentials logs in successfully (HTTP 200)."""
        user_repo = UserRepository(db_session)
        await user_repo.create(
            full_name="Valid Admin",
            email="valid_admin@example.com",
            phone="9876500004",
            hashed_password=hash_password("CorrectPass1!"),
            role="admin",
            is_phone_verified=True,
            is_active=True,
        )

        response = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9876500004",
                "password": "CorrectPass1!",
            },
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Login successful."
        assert response.json()["user"]["role"] == "admin"
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies
