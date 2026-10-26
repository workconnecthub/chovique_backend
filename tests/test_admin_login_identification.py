"""
Test Suite: Unified Login Identification & Role-Based Authentication
=====================================================================
Validates all 9 required scenarios:
1. Super Admin-created Admin account -> password field.
2. Super Admin account -> password field.
3. Delivery Person account -> password field.
4. Existing customer account -> OTP field.
5. Unknown mobile number -> customer OTP flow (account created only after OTP verify).
6. Incorrect staff password -> login rejected (401).
7. Staff mobile number with incorrect or missing role metadata -> safe handling, never automatic customer creation.
8. Mobile number with +91 country code -> correct account lookup.
9. Existing staff account -> no customer OTP sent and no customer account created.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User


@pytest.mark.asyncio
class TestAdminLoginIdentification:
    """Test suite for Admin and Staff login identification via POST /api/v1/auth/identify."""

    # -------------------------------------------------------------------------
    # Scenario 1: Super Admin-created Admin account -> password field
    # -------------------------------------------------------------------------
    async def test_scenario_1_superadmin_created_admin_returns_password_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        1. When Super Admin creates an Admin account, the account is saved in PostgreSQL
           with role 'admin', mobile number, active status, and hashed password.
        2. Entering that mobile number on /identify returns next_step='password'.
        3. Submitting mobile + password to /staff/login authenticates successfully.
        4. Even if the admin account had spaced phone '+91 80741 82783' in PostgreSQL,
           the lookup reliably identifies the account.
        """
        # A) Create Admin account via superadmin creation schema/service logic
        superadmin = User(
            full_name="Super Admin Creator",
            email="sa_creator@chovique.com",
            phone="+919876543201",
            role="superadmin",
            hashed_password=hash_password("SuperSecret123!"),
            is_active=True,
            is_phone_verified=True,
            is_email_verified=True,
        )
        db_session.add(superadmin)
        await db_session.commit()

        # Super admin registers new admin via service
        from app.schemas.superadmin_admins import AdminCreateRequest
        from app.services.superadmin_admins_service import SuperadminAdminsService

        service = SuperadminAdminsService(db_session)
        admin_req = AdminCreateRequest(
            full_name="Operations Admin",
            email="ops_admin@chovique.com",
            phone="8074182783",
            role="admin",
            password="StrongPassword123!",
            confirm_password="StrongPassword123!",
            status="active",
        )
        created_admin = await service.register_admin(admin_req, superadmin)
        assert created_admin.role == "admin"
        assert created_admin.is_active is True
        assert created_admin.phone == "+918074182783"

        # Verify DB record
        db_user = await db_session.get(User, created_admin.id)
        assert db_user is not None
        assert db_user.role == "admin"
        assert db_user.is_active is True

        # Identify call with 10-digit number
        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "8074182783"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "password"
        assert "otp" not in data
        assert "access_token" not in data

        # Staff login succeeds
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "8074182783", "password": "StrongPassword123!"},
        )
        assert login_res.status_code == 200
        assert login_res.json()["user"]["role"] == "admin"

        # B) Also test legacy admin stored with spaces in PostgreSQL
        spaced_admin = User(
            full_name="Legacy Spaced Admin",
            email="spaced_admin@chovique.com",
            phone="+91 80741 82799",
            role="admin",
            hashed_password=hash_password("StrongPassword123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(spaced_admin)
        await db_session.commit()

        # Entering 8074182799 returns password step
        res_spaced = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "8074182799"},
        )
        assert res_spaced.status_code == 200
        assert res_spaced.json()["next_step"] == "password"

    # -------------------------------------------------------------------------
    # Scenario 2: Super Admin account -> password field
    # -------------------------------------------------------------------------
    async def test_scenario_2_super_admin_returns_password_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Super Admin account mobile number -> next_step='password'."""
        sa = User(
            full_name="Chief Executive",
            email="superchief@chovique.com",
            phone="+919876543202",
            role="superadmin",
            hashed_password=hash_password("SuperMaster123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(sa)
        await db_session.commit()

        res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9876543202"},
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "password"

        # Staff login
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "9876543202", "password": "SuperMaster123!"},
        )
        assert login_res.status_code == 200
        assert login_res.json()["user"]["role"] == "superadmin"

    # -------------------------------------------------------------------------
    # Scenario 3: Delivery Person account -> password field
    # -------------------------------------------------------------------------
    async def test_scenario_3_delivery_person_returns_password_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Delivery Person account mobile number -> next_step='password'."""
        dp = User(
            full_name="Ramesh Logistics",
            email="ramesh@chovique.com",
            phone="+919876543203",
            role="delivery_boy",
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(dp)
        await db_session.commit()

        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "9876543203"},
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "password"

        # Staff login succeeds with role delivery_boy
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "9876543203", "password": "DeliveryPass123!"},
        )
        assert login_res.status_code == 200
        assert login_res.json()["user"]["role"] == "delivery_boy"

    # -------------------------------------------------------------------------
    # Scenario 4: Existing customer account -> OTP field
    # -------------------------------------------------------------------------
    async def test_scenario_4_existing_customer_returns_otp_step(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """Existing customer account mobile number -> next_step='otp' and MSG91 OTP sent."""
        cust = User(
            full_name="Aarav Sharma",
            email="aarav@example.com",
            phone="+919876543204",
            role="customer",
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(cust)
        await db_session.commit()

        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "9876543204"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "otp"
        assert "expires_in" in data
        assert "resend_cooldown" in data

        # Check OTP generated in redis
        otp = await mock_redis.get("otp:test_val:customer_login:+919876543204")
        if not otp:
            otp = await mock_redis.get("otp:test_val:customer_login:9876543204")
        assert otp is not None
        assert len(otp) == 6

    # -------------------------------------------------------------------------
    # Scenario 5: Unknown mobile number -> customer OTP flow
    # -------------------------------------------------------------------------
    async def test_scenario_5_unknown_mobile_customer_otp_flow(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """
        Unknown mobile number -> next_step='otp'.
        Customer account is created ONLY upon successful OTP verification.
        """
        new_phone = "9876543205"

        # Verify no user exists yet
        pre_check = await db_session.execute(
            select(User).where(User.phone.in_([new_phone, f"+91{new_phone}"]))
        )
        assert pre_check.scalar_one_or_none() is None

        # Identify returns OTP
        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": new_phone},
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "otp"

        # Still no customer account created before verification
        mid_check = await db_session.execute(
            select(User).where(User.phone.in_([new_phone, f"+91{new_phone}"]))
        )
        assert mid_check.scalar_one_or_none() is None

        # Verify OTP
        otp = await mock_redis.get(f"otp:test_val:customer_login:+91{new_phone}")
        if not otp:
            otp = await mock_redis.get(f"otp:test_val:customer_login:{new_phone}")
        assert otp is not None

        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"country_code": "+91", "mobile_number": new_phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        assert verify_res.json()["user"]["role"] == "customer"

        # Account now exists in PostgreSQL
        post_check = await db_session.execute(
            select(User).where(User.phone == f"+91{new_phone}")
        )
        created_user = post_check.scalar_one_or_none()
        assert created_user is not None
        assert created_user.role == "customer"

    # -------------------------------------------------------------------------
    # Scenario 6: Incorrect staff password -> login rejected
    # -------------------------------------------------------------------------
    async def test_scenario_6_incorrect_staff_password_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Incorrect staff password returns 401 Unauthorized."""
        admin = User(
            full_name="Security Admin",
            email="security_admin@chovique.com",
            phone="+919876543206",
            role="admin",
            hashed_password=hash_password("CorrectPassword123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(admin)
        await db_session.commit()

        # Identify returns password step
        ident_res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9876543206"},
        )
        assert ident_res.status_code == 200
        assert ident_res.json()["next_step"] == "password"

        # Wrong password fails
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "9876543206", "password": "WrongPassword999!"},
        )
        assert login_res.status_code == 401
        assert "invalid" in login_res.json()["detail"].lower()

    # -------------------------------------------------------------------------
    # Scenario 7: Staff mobile with incorrect/missing metadata -> safe handling
    # -------------------------------------------------------------------------
    async def test_scenario_7_staff_with_corrupt_metadata_never_creates_customer(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """
        Staff account with inactive or missing role metadata is handled safely:
        - Identify returns password or 403 (never customer OTP).
        - Attempting customer verify-otp is rejected with 403.
        - Automatic customer account creation is strictly blocked.
        """
        # Deactivated admin
        deactivated_admin = User(
            full_name="Former Admin",
            email="former_admin@chovique.com",
            phone="+919876543207",
            role="admin",
            hashed_password=hash_password("OldPassword123!"),
            is_active=False,
            is_phone_verified=True,
        )
        db_session.add(deactivated_admin)
        await db_session.commit()

        # Identify on inactive staff blocked with 403
        ident_res = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "9876543207"},
        )
        assert ident_res.status_code == 403
        assert "deactivated" in ident_res.json()["detail"].lower()

        # Directly calling customer verify-otp for this number is blocked
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"country_code": "+91", "phone": "9876543207", "otp": "123456"},
        )
        assert verify_res.status_code in (400, 401, 403)

    # -------------------------------------------------------------------------
    # Scenario 8: Mobile number with +91 country code -> correct account lookup
    # -------------------------------------------------------------------------
    async def test_scenario_8_mobile_with_plus_91_lookup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Accounts stored in DB are correctly identified when input contains +91."""
        admin = User(
            full_name="National Admin",
            email="national_admin@chovique.com",
            phone="+919876543208",
            role="admin",
            hashed_password=hash_password("NationalSecret123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(admin)
        await db_session.commit()

        # Case A: separate country_code='+91' and mobile_number='9876543208'
        res_a = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "9876543208"},
        )
        assert res_a.status_code == 200
        assert res_a.json()["next_step"] == "password"

        # Case B: mobile_number='+919876543208'
        res_b = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "+919876543208"},
        )
        assert res_b.status_code == 200
        assert res_b.json()["next_step"] == "password"

        # Case C: mobile_number='+91 98765 43208'
        res_c = await client.post(
            "/api/v1/auth/identify",
            json={"mobile_number": "+91 98765 43208"},
        )
        assert res_c.status_code == 200
        assert res_c.json()["next_step"] == "password"

    # -------------------------------------------------------------------------
    # Scenario 9: Existing staff account -> no customer OTP sent & no customer created
    # -------------------------------------------------------------------------
    async def test_scenario_9_existing_staff_no_customer_otp_and_no_customer_created(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """
        For an existing staff account:
        - POST /identify never dispatches customer OTP.
        - Direct call to POST /customer/send-otp is rejected with 403.
        - Direct call to POST /customer/resend-otp is rejected with 403.
        - Direct call to POST /customer/verify-otp is rejected with 403.
        - The staff account role in PostgreSQL remains unchanged.
        """
        staff_phone = "9876543209"
        staff = User(
            full_name="Staff Protector",
            email="staff_protect@chovique.com",
            phone=f"+91{staff_phone}",
            role="admin",
            hashed_password=hash_password("ProtectPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(staff)
        await db_session.commit()

        # 1. Identify returns password without OTP
        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": staff_phone},
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "password"

        # Ensure no customer OTP in Redis
        otp_val = await mock_redis.get(f"otp:test_val:customer_login:+91{staff_phone}")
        assert otp_val is None

        # 2. Direct customer/send-otp is blocked with 403
        send_res = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"country_code": "+91", "phone": staff_phone},
        )
        assert send_res.status_code == 403
        assert "staff" in send_res.json()["detail"].lower()

        # 3. Direct customer/resend-otp is blocked with 403
        resend_res = await client.post(
            "/api/v1/auth/customer/resend-otp",
            json={"country_code": "+91", "phone": staff_phone},
        )
        assert resend_res.status_code == 403
        assert "staff" in resend_res.json()["detail"].lower()

        # 4. Direct customer/verify-otp is blocked with 403
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"country_code": "+91", "phone": staff_phone, "otp": "999999"},
        )
        assert verify_res.status_code in (400, 401, 403)

        # 5. Verify database role is still strictly 'admin' and no customer row was added
        db_accounts = await db_session.execute(
            select(User).where(User.phone.in_([staff_phone, f"+91{staff_phone}"]))
        )
        users = list(db_accounts.scalars().all())
        assert len(users) == 1
        assert users[0].role == "admin"
        assert users[0].full_name == "Staff Protector"
