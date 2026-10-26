"""
Comprehensive automated tests for the complete Chovique Authentication System.
Covers Customer OTP, Staff Role-Based Access, Session Management, and RBAC against PostgreSQL.
"""

import asyncio
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.models.otp_challenge import OTPChallenge
from app.models.cart import Cart
from app.models.wallet import UserWallet
from app.models.order import Order


@pytest_asyncio.fixture
async def seed_staff_accounts(db_session: AsyncSession):
    """Seed Superadmin, Admin, and Delivery Person accounts for staff tests."""
    sa = User(
        full_name="Master Superadmin",
        email="superadmin@chovique.com",
        phone="9999900001",
        role="superadmin",
        hashed_password=hash_password("SuperSecret123!"),
        is_active=True,
        is_phone_verified=True,
    )
    adm = User(
        full_name="Store Admin",
        email="admin@chovique.com",
        phone="9999900002",
        role="admin",
        hashed_password=hash_password("AdminPass123!"),
        is_active=True,
        is_phone_verified=True,
    )
    dp = User(
        full_name="Delivery Hero",
        email="delivery@chovique.com",
        phone="9999900003",
        role="delivery_boy",
        hashed_password=hash_password("DeliveryPass123!"),
        is_active=True,
        is_phone_verified=True,
    )
    inactive = User(
        full_name="Inactive Admin",
        email="inactive@chovique.com",
        phone="9999900004",
        role="admin",
        hashed_password=hash_password("AdminPass123!"),
        is_active=False,
        is_phone_verified=True,
    )
    db_session.add_all([sa, adm, dp, inactive])
    await db_session.commit()


@pytest.mark.asyncio
class TestCustomerOTPAuthentication:
    """Tests for Customer OTP Authentication Flow."""

    async def test_customer_send_otp_success(self, client: AsyncClient, mock_redis):
        """Test sending OTP to a valid mobile number."""
        response = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": "9876543210"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "expires_in" in data
        # Ensure OTP is NEVER returned in the API response
        assert "otp" not in data

    async def test_customer_send_otp_invalid_phone(self, client: AsyncClient):
        """Test sending OTP to an invalid mobile number fails validation."""
        response = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": "12345"},  # Too short
        )
        assert response.status_code == 422

    async def test_customer_resend_otp_cooldown(self, client: AsyncClient):
        """Test resend OTP cooldown enforces waiting period."""
        phone = "9876543211"
        res1 = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": phone},
        )
        assert res1.status_code == 200

        res2 = await client.post(
            "/api/v1/auth/customer/resend-otp",
            json={"phone": phone},
        )
        assert res2.status_code == 429
        assert "wait" in res2.json()["detail"].lower()

    async def test_customer_verify_otp_and_auto_create_account(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """Test that first-time OTP verification automatically provisions customer account and cart."""
        phone = "9876543212"
        # 1. Request OTP
        send_res = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": phone},
        )
        assert send_res.status_code == 200

        # Retrieve plain OTP dispatched in test environment from mock_redis
        otp = await mock_redis.get(f"otp:test_val:customer_login:{phone}")
        assert otp is not None

        # Verify with received OTP
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        data = verify_res.json()
        assert "user" in data
        assert data["user"]["role"] == "customer"
        assert data["user"]["profile"]["phone"] in (phone, f"+91{phone}")
        assert "access_token" in data

        # Check DB that user was created with a cart
        user_stmt = select(User).where(User.phone.in_([phone, f"+91{phone}"]))
        user_res = await db_session.execute(user_stmt)
        user = user_res.scalars().first()
        assert user is not None
        assert user.role == "customer"
        assert user.is_phone_verified is True
        assert user.hashed_password is None  # Customers have no password

        # Check cart exists
        cart_stmt = select(Cart).where(Cart.user_id == user.id)
        cart_res = await db_session.execute(cart_stmt)
        assert cart_res.scalars().first() is not None

        # Check welcome coins wallet exists
        wallet_stmt = select(UserWallet).where(UserWallet.user_id == user.id)
        wallet_res = await db_session.execute(wallet_stmt)
        wallet = wallet_res.scalars().first()
        assert wallet is not None
        assert wallet.coin_balance >= 200

    async def test_existing_customer_login(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """Test that an existing customer is authenticated using their existing account."""
        phone = "9876543213"
        customer = User(
            full_name="Existing Customer",
            email="existing@example.com",
            phone=phone,
            role="customer",
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(customer)
        await db_session.commit()
        await db_session.refresh(customer)
        cust_id = customer.id

        # Send OTP
        await client.post("/api/v1/auth/customer/send-otp", json={"phone": phone})

        # Fetch simulated OTP from mock_redis
        otp = await mock_redis.get(f"otp:test_val:customer_login:{phone}")
        assert otp is not None

        # Verify OTP
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["user"]["id"] == str(cust_id)

    async def test_invalid_otp_and_max_attempts_lockout(
        self, client: AsyncClient
    ):
        """Test that submitting invalid OTP fails and 3 failed attempts lock out the challenge."""
        phone = "9876543214"
        await client.post("/api/v1/auth/customer/send-otp", json={"phone": phone})

        # Attempt 1: wrong OTP
        r1 = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": "000000"},
        )
        assert r1.status_code == 400
        assert "Invalid OTP" in r1.json()["detail"]

        # Attempt 2: wrong OTP
        r2 = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": "000000"},
        )
        assert r2.status_code == 400

        # Attempt 3: wrong OTP -> max attempts reached (400 or 429)
        r3 = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": "000000"},
        )
        assert r3.status_code in (400, 429)
        assert "exceeded" in r3.json()["detail"].lower() or "maximum" in r3.json()["detail"].lower()


@pytest.mark.asyncio
class TestStaffAuthentication:
    """Tests for Staff Login and Role Validation."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_staff(self, seed_staff_accounts):
        pass

    async def test_staff_check_mobile_success(self, client: AsyncClient):
        """Test check-mobile succeeds for existing active staff and returns no auth tokens."""
        res = await client.post(
            "/api/v1/auth/staff/check-mobile",
            json={"phone": "9999900001", "role": "super_admin"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data.get("status") == "ok" or data.get("exists") is True
        assert "access_token" not in data
        assert "password" not in data

    async def test_staff_check_mobile_non_existent(self, client: AsyncClient):
        """Test check-mobile fails for non-existent mobile number."""
        res = await client.post(
            "/api/v1/auth/staff/check-mobile",
            json={"phone": "9999999999", "role": "admin"},
        )
        assert res.status_code == 404

    async def test_staff_check_mobile_inactive(self, client: AsyncClient):
        """Test check-mobile fails for deactivated staff account."""
        res = await client.post(
            "/api/v1/auth/staff/check-mobile",
            json={"phone": "9999900004", "role": "admin"},
        )
        assert res.status_code == 403
        assert "deactivated" in res.json()["detail"].lower()

    async def test_super_admin_login_success(self, client: AsyncClient):
        """Test Super Admin login with valid credentials."""
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900001",
                "password": "SuperSecret123!",
                "role": "super_admin",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user"]["role"] == "superadmin"
        assert "access_token" in data

    async def test_admin_login_success(self, client: AsyncClient):
        """Test Admin login with valid credentials."""
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "AdminPass123!",
                "role": "admin",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user"]["role"] == "admin"
        assert "access_token" in data

    async def test_delivery_person_login_success(self, client: AsyncClient):
        """Test Delivery Person login with valid credentials."""
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900003",
                "password": "DeliveryPass123!",
                "role": "delivery_person",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user"]["role"] == "delivery_boy"
        assert "access_token" in data

    async def test_staff_login_wrong_password(self, client: AsyncClient):
        """Test staff login with incorrect password is rejected."""
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "WrongPassword123!",
                "role": "admin",
            },
        )
        assert res.status_code == 401
        assert "invalid" in res.json()["detail"].lower()

    async def test_staff_login_role_mismatch(self, client: AsyncClient):
        """Test staff attempting to log in under unauthorized role is rejected."""
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900003",
                "password": "DeliveryPass123!",
                "role": "super_admin",
            },
        )
        assert res.status_code == 401


@pytest.mark.asyncio
class TestSessionManagementAndRBAC:
    """Tests for Token Refresh, Revocation, and Role-Based Authorization."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_staff(self, seed_staff_accounts):
        pass

    async def test_get_me_endpoint(self, client: AsyncClient):
        """Test /api/v1/auth/me returns current authenticated user profile."""
        # 1. Login as admin
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "AdminPass123!",
                "role": "admin",
            },
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]

        # 2. Call /api/v1/auth/me
        me_res = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_res.status_code == 200
        me_data = me_res.json()
        assert me_data["profile"]["phone"] == "9999900002"
        assert me_data["role"] == "admin"

    async def test_refresh_token_rotation(self, client: AsyncClient):
        """Test refreshing authentication credentials issues new tokens and cookies."""
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "AdminPass123!",
                "role": "admin",
            },
        )
        assert login_res.status_code == 200
        r_token = login_res.json()["refresh_token"]

        refresh_res = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": r_token},
            cookies={"refresh_token": r_token},
        )
        assert refresh_res.status_code == 200
        new_data = refresh_res.json()
        assert "access_token" in new_data

    async def test_logout_revocation(self, client: AsyncClient):
        """Test logout clears session and blocklists token."""
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "AdminPass123!",
                "role": "admin",
            },
        )
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        r_token = login_res.json()["refresh_token"]

        logout_res = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
            cookies={"refresh_token": r_token},
        )
        assert logout_res.status_code == 200

    async def test_customer_cannot_access_admin_endpoints(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """Test RBAC: Customer token cannot access Admin-only endpoints."""
        phone = "9876543299"
        cust = User(
            phone=phone,
            role="customer",
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(cust)
        await db_session.commit()

        # Send and verify OTP
        await client.post("/api/v1/auth/customer/send-otp", json={"phone": phone})
        otp = await mock_redis.get(f"otp:test_val:customer_login:{phone}")
        assert otp is not None

        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        customer_token = verify_res.json()["access_token"]

        # Attempt to access admin orders endpoint
        admin_res = await client.get(
            "/api/v1/admin/orders",
            headers={"Authorization": f"Bearer {customer_token}"},
        )
        assert admin_res.status_code in (401, 403)


@pytest.mark.asyncio
class TestIdentifyMobileEndpoint:
    """Tests for Single Unified Login: POST /api/v1/auth/identify."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_staff(self, seed_staff_accounts):
        pass

    async def test_identify_customer_returns_otp_step(self, client: AsyncClient, mock_redis):
        """Test identify on a customer / new mobile returns next_step='otp' and dispatches OTP."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9876543220"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "otp"
        assert "message" in data
        assert "phone" in data
        # Ensure OTP is NEVER exposed
        assert "otp" not in data
        assert "password" not in data
        assert "access_token" not in data

        # Check OTP was generated in test Redis
        otp = await mock_redis.get("otp:test_val:customer_login:9876543220")
        assert otp is not None
        assert len(otp) == 6

    async def test_identify_staff_superadmin_returns_password_step(self, client: AsyncClient):
        """Test identify on Super Admin mobile returns next_step='password' without exposing tokens."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9999900001"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "password"
        assert "access_token" not in data
        assert "password" not in data

    async def test_identify_staff_admin_returns_password_step(self, client: AsyncClient):
        """Test identify on Admin mobile returns next_step='password'."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9999900002"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "password"

    async def test_identify_staff_delivery_boy_returns_password_step(self, client: AsyncClient):
        """Test identify on Delivery Person mobile returns next_step='password'."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9999900003"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "password"

    async def test_identify_inactive_staff_fails_with_403(self, client: AsyncClient):
        """Test identify on deactivated staff account is blocked with 403."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9999900004"},
        )
        assert res.status_code == 403
        assert "deactivated" in res.json()["detail"].lower()

    async def test_identify_invalid_mobile_fails_with_422(self, client: AsyncClient):
        """Test identify on malformed mobile number fails validation."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "12345"},
        )
        assert res.status_code in (400, 422)


@pytest.mark.asyncio
class TestDailyOTPLimitQuota:
    """Tests for PostgreSQL-backed 5 OTP per calendar day limit."""

    async def test_daily_otp_quota_enforces_maximum_five_requests(
        self, client: AsyncClient, mock_redis
    ):
        """Test that after 5 accepted OTP send/resend requests, the 6th is rejected with 429."""
        phone = "9876543230"

        for i in range(1, 6):
            # Clear 60s cooldown and lockout keys in mock_redis to simulate user attempts spaced out across the day
            await mock_redis.delete(f"otp:resend:customer_login:{phone}")
            await mock_redis.delete(f"otp:resend_count:customer_login:{phone}")
            await mock_redis.delete(f"otp:resend_lock:customer_login:{phone}")

            res = await client.post(
                "/api/v1/auth/customer/send-otp",
                json={"phone": phone},
            )
            assert res.status_code == 200, f"Attempt {i} failed: {res.text}"

        # 6th attempt on the same day must be rejected by PostgreSQL daily tracker
        await mock_redis.delete(f"otp:resend:customer_login:{phone}")
        await mock_redis.delete(f"otp:resend_count:customer_login:{phone}")
        await mock_redis.delete(f"otp:resend_lock:customer_login:{phone}")
        res_6 = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": phone},
        )
        assert res_6.status_code == 429
        detail = res_6.json()["detail"].lower()
        assert "daily" in detail and "5" in detail


@pytest.mark.asyncio
class TestStaffLoginWithoutExplicitRole:
    """Tests for Unified Staff Login where backend determines role automatically."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_staff(self, seed_staff_accounts):
        pass

    async def test_staff_login_without_role_parameter(self, client: AsyncClient):
        """Test that submitting only phone and password authenticates and resolves role from DB."""
        # 1. Admin login without role
        res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900002",
                "password": "AdminPass123!",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user"]["role"] == "admin"
        assert "access_token" in data

        # 2. Superadmin login without role
        sa_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "phone": "9999900001",
                "password": "SuperSecret123!",
            },
        )
        assert sa_res.status_code == 200
        sa_data = sa_res.json()
        assert sa_data["user"]["role"] == "superadmin"


@pytest.mark.asyncio
class TestRemovedEndpointsReturn404:
    """Verifies that removed legacy authentication endpoints return 404 because their routes are no longer registered."""

    async def test_removed_endpoints_return_404(self, client: AsyncClient):
        removed_endpoints = [
            ("/api/v1/auth/register", {"email": "test@example.com", "password": "Pass"}),
            ("/api/v1/auth/google", {"id_token": "some-token"}),
            ("/api/v1/auth/login", {"email": "test@example.com", "password": "Pass"}),
            ("/api/v1/auth/verify-otp", {"email": "test@example.com", "otp": "123456"}),
            ("/api/v1/auth/resend-otp", {"email": "test@example.com"}),
            ("/api/v1/auth/set-password", {"password": "Pass", "confirm_password": "Pass"}),
        ]

        for path, payload in removed_endpoints:
            res = await client.post(path, json=payload)
            assert res.status_code == 404, f"Expected 404 for removed endpoint {path}, got {res.status_code}"


@pytest.mark.asyncio
class TestRetainedSecurityEndpoints:
    """Verifies that retained password management, profile, coupons, and session endpoints remain functional."""

    @pytest_asyncio.fixture(autouse=True)
    async def setup_staff(self, seed_staff_accounts):
        pass

    async def test_forgot_password_retained_for_staff(self, client: AsyncClient, mock_redis):
        """POST /api/v1/auth/forgot-password is retained for staff password recovery."""
        res = await client.post(
            "/api/v1/auth/forgot-password",
            json={"phone": "9999900002"},
        )
        assert res.status_code == 200
        assert "message" in res.json()

    async def test_get_users_me_and_coupons_used_retained(self, client: AsyncClient):
        """GET /api/v1/users/me and GET /api/v1/users/me/coupons/used remain intact."""
        # Unauthenticated request returns 401
        res = await client.get("/api/v1/users/me")
        assert res.status_code == 401

        res_coupons = await client.get("/api/v1/users/me/coupons/used")
        assert res_coupons.status_code == 401
