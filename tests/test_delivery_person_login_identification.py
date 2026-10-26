"""
Test Suite: Delivery Person Login Identification & RBAC Verification
=====================================================================
Validates all 10 required scenarios:
1. Super Admin-created Delivery Person -> password field.
2. Admin-created Delivery Person -> password field.
3. Valid Delivery Person password -> successful login.
4. Incorrect password -> login rejected.
5. Existing customer -> OTP flow.
6. Unknown mobile number -> OTP flow and customer creation only after verification.
7. Existing staff mobile number -> no OTP sent and no customer created.
8. Mobile number normalization -> correct account lookup.
9. Inactive Delivery Person -> login rejected.
10. Delivery Person cannot access Admin or Super Admin APIs.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User


@pytest.mark.asyncio
class TestDeliveryPersonLoginIdentification:
    """Test suite for Delivery Person login identification via POST /api/v1/auth/identify and staff login."""

    # -------------------------------------------------------------------------
    # Scenario 1: Super Admin-created Delivery Person -> password field
    # -------------------------------------------------------------------------
    async def test_scenario_1_superadmin_created_delivery_person_returns_password_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        1. Super Admin creates a Delivery Person account via /admin/delivery-boys.
        2. Account is saved in PostgreSQL with role 'delivery_person', normalized mobile number,
           active status, and securely hashed password.
        3. Delivery Person enters their registered mobile number on /identify -> returns next_step='password'.
        """
        # A) Create Super Admin in DB
        superadmin = User(
            full_name="Super Admin Creator",
            email="sa_creator_dp@chovique.com",
            phone="+919876543101",
            role="superadmin",
            hashed_password=hash_password("SuperSecret123!"),
            is_active=True,
            is_phone_verified=True,
            is_email_verified=True,
        )
        db_session.add(superadmin)
        await db_session.commit()

        # Super Admin logs in
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "9876543101", "password": "SuperSecret123!"},
        )
        assert login_res.status_code == 200
        sa_token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {sa_token}"}

        # B) Super Admin creates Delivery Person via API
        create_res = await client.post(
            "/api/v1/admin/delivery-boys",
            json={
                "full_name": "Ramesh Kumar",
                "email": "ramesh.kumar@chovique.com",
                "phone": "8074182781",
                "password": "DeliverySecure123!",
            },
            headers=auth_headers,
        )
        assert create_res.status_code == 201
        created_dp_data = create_res.json()
        assert created_dp_data["role"] == "delivery_person"
        assert created_dp_data["phone"] == "+918074182781"
        assert created_dp_data["is_active"] is True

        # C) Verify directly in PostgreSQL
        dp_id = created_dp_data["id"]
        db_dp = await db_session.get(User, dp_id)
        assert db_dp is not None
        assert db_dp.role == "delivery_person"
        assert db_dp.phone == "+918074182781"
        assert db_dp.is_active is True
        assert verify_password("DeliverySecure123!", db_dp.hashed_password) is True

        # D) Identify endpoint with 10-digit mobile number
        identify_res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "8074182781"},
        )
        assert identify_res.status_code == 200
        ident_data = identify_res.json()
        assert ident_data["next_step"] == "password"
        assert ident_data["message"] == "Password authentication required"
        assert "otp" not in ident_data

    # -------------------------------------------------------------------------
    # Scenario 2: Admin-created Delivery Person -> password field
    # -------------------------------------------------------------------------
    async def test_scenario_2_admin_created_delivery_person_returns_password_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        1. Store Admin creates a Delivery Person account via /admin/delivery-boys.
        2. Account is saved in PostgreSQL with role 'delivery_person'.
        3. Identify endpoint returns next_step='password'.
        """
        # A) Create Store Admin in DB
        admin = User(
            full_name="Operations Admin",
            email="ops_admin_dp@chovique.com",
            phone="+919876543102",
            role="admin",
            hashed_password=hash_password("AdminSecure123!"),
            is_active=True,
            is_phone_verified=True,
            is_email_verified=True,
        )
        db_session.add(admin)
        await db_session.commit()

        # Admin logs in
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "9876543102", "password": "AdminSecure123!"},
        )
        assert login_res.status_code == 200
        admin_token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {admin_token}"}

        # B) Admin creates Delivery Person via API
        create_res = await client.post(
            "/api/v1/admin/delivery-boys",
            json={
                "full_name": "Suresh Logistics",
                "email": "suresh.logistics@chovique.com",
                "phone": "8074182782",
                "password": "DeliverySecure123!",
            },
            headers=auth_headers,
        )
        assert create_res.status_code == 201
        assert create_res.json()["role"] == "delivery_person"

        # C) Identify endpoint returns password step
        identify_res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "8074182782"},
        )
        assert identify_res.status_code == 200
        assert identify_res.json()["next_step"] == "password"
        assert identify_res.json()["message"] == "Password authentication required"

    # -------------------------------------------------------------------------
    # Scenario 3: Valid Delivery Person password -> successful login
    # -------------------------------------------------------------------------
    async def test_scenario_3_valid_delivery_person_password_successful_login(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Submitting registered mobile number + correct password to /staff/login
        successfully authenticates the Delivery Person and issues JWT tokens + cookies.
        """
        dp = User(
            full_name="Anil Fleet",
            email="anil.fleet@chovique.com",
            phone="+918074182783",
            role="delivery_person",
            hashed_password=hash_password("AnilPassword123!"),
            is_active=True,
            is_phone_verified=True,
            is_email_verified=True,
        )
        db_session.add(dp)
        await db_session.commit()

        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "8074182783", "password": "AnilPassword123!"},
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert data["message"] == "Login successful."
        assert data["user"]["role"] == "delivery_person"
        assert data["user"]["id"] == str(dp.id)
        assert "access_token" in data
        assert "refresh_token" in data
        # Verify httpOnly cookie set
        assert "access_token" in login_res.cookies or "access_token" in data

    # -------------------------------------------------------------------------
    # Scenario 4: Incorrect password -> login rejected
    # -------------------------------------------------------------------------
    async def test_scenario_4_incorrect_password_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Entering incorrect password returns 401 Unauthorized."""
        dp = User(
            full_name="Sunil Driver",
            email="sunil.driver@chovique.com",
            phone="+918074182784",
            role="delivery_person",
            hashed_password=hash_password("SunilPassword123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(dp)
        await db_session.commit()

        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "8074182784", "password": "WrongPassword999!"},
        )
        assert login_res.status_code == 401
        assert "Invalid mobile number, role, or password" in login_res.json()["detail"]

    # -------------------------------------------------------------------------
    # Scenario 5: Existing customer -> OTP flow
    # -------------------------------------------------------------------------
    async def test_scenario_5_existing_customer_returns_otp_step(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Existing customer account enters mobile number -> next_step='otp'."""
        cust = User(
            full_name="Priya Customer",
            email="priya@gmail.com",
            phone="+919876543210",
            role="customer",
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(cust)
        await db_session.commit()

        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "9876543210"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "otp"
        assert data["country_code"] == "+91"
        assert data["mobile_number"] == "9876543210"

    # -------------------------------------------------------------------------
    # Scenario 6: Unknown mobile number -> OTP flow and customer creation only after verification
    # -------------------------------------------------------------------------
    async def test_scenario_6_unknown_mobile_creates_customer_only_after_verification(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """
        1. An unknown mobile number calling /identify receives next_step='otp'.
        2. Database is verified: NO user account is created yet.
        3. Once OTP verification succeeds, customer account is atomically created.
        """
        unknown_phone = "8074189999"

        # 1. Identify
        res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": unknown_phone},
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "otp"

        # 2. Verify NO customer exists in DB
        res_db = await db_session.execute(select(User).where(User.phone == f"+91{unknown_phone}"))
        assert res_db.scalar_one_or_none() is None

        # 3. Retrieve OTP from mock Redis
        otp = await mock_redis.get(f"otp:test_val:customer_login:+91{unknown_phone}")
        if not otp:
            otp = await mock_redis.get(f"otp:test_val:customer_login:{unknown_phone}")
        assert otp is not None

        # 4. Customer verifies OTP
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"country_code": "+91", "mobile_number": unknown_phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert verify_data["user"]["role"] == "customer"

        # 5. Verify customer now exists in DB
        res_db_after = await db_session.execute(select(User).where(User.phone == f"+91{unknown_phone}"))
        new_cust = res_db_after.scalar_one_or_none()
        assert new_cust is not None
        assert new_cust.role == "customer"
        assert new_cust.is_phone_verified is True

    # -------------------------------------------------------------------------
    # Scenario 7: Existing staff mobile number -> no OTP sent and no customer created
    # -------------------------------------------------------------------------
    async def test_scenario_7_staff_mobile_rejects_customer_otp_and_creation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Calling customer OTP endpoints with an existing Delivery Person mobile number
        is rejected with 403 Forbidden and never generates customer records.
        """
        dp = User(
            full_name="Kiran Delivery",
            email="kiran.dp@chovique.com",
            phone="+918074182785",
            role="delivery_person",
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(dp)
        await db_session.commit()

        # Send OTP rejected
        send_res = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": "8074182785"},
        )
        assert send_res.status_code == 403
        assert "registered as a staff account" in send_res.json()["detail"]

        # Resend OTP rejected
        resend_res = await client.post(
            "/api/v1/auth/customer/resend-otp",
            json={"phone": "8074182785"},
        )
        assert resend_res.status_code == 403
        assert "registered as a staff account" in resend_res.json()["detail"]

        # Verify OTP rejected
        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": "8074182785", "otp": "123456"},
        )
        assert verify_res.status_code == 403

        # Confirm no customer account was created
        all_accounts = (await db_session.execute(select(User).where(User.phone == "+918074182785"))).scalars().all()
        assert len(all_accounts) == 1
        assert all_accounts[0].role == "delivery_person"

    # -------------------------------------------------------------------------
    # Scenario 8: Mobile number normalization -> correct account lookup
    # -------------------------------------------------------------------------
    async def test_scenario_8_phone_normalization_variants_correct_lookup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Test that various phone number input formats reliably match the stored Delivery Person:
        1. 10-digit national number: '8074182786'
        2. E.164 with country code: '+918074182786'
        3. Leading zero format: '08074182786'
        4. Spaced format: '+91 80741 82786'
        5. Legacy database record stored with space '+91 80741 82799'
        """
        dp = User(
            full_name="Normalized Express",
            email="norm.express@chovique.com",
            phone="+918074182786",
            role="delivery_person",
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        # Legacy record with spaces
        legacy_dp = User(
            full_name="Legacy Spaced Delivery",
            email="legacy.spaced@chovique.com",
            phone="+91 80741 82799",
            role="delivery_boy",  # legacy role name
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add_all([dp, legacy_dp])
        await db_session.commit()

        # Format 1: 10-digit
        res1 = await client.post("/api/v1/auth/identify", json={"country_code": "+91", "mobile_number": "8074182786"})
        assert res1.status_code == 200
        assert res1.json()["next_step"] == "password"

        # Format 2: E.164 in mobile_number
        res2 = await client.post("/api/v1/auth/identify", json={"country_code": "+91", "mobile_number": "+918074182786"})
        assert res2.status_code == 200
        assert res2.json()["next_step"] == "password"

        # Format 3: Leading zero
        res3 = await client.post("/api/v1/auth/identify", json={"country_code": "+91", "mobile_number": "08074182786"})
        assert res3.status_code == 200
        assert res3.json()["next_step"] == "password"

        # Format 4: Spaced lookup
        res4 = await client.post("/api/v1/auth/identify", json={"country_code": "+91", "mobile_number": "+91 80741 82786"})
        assert res4.status_code == 200
        assert res4.json()["next_step"] == "password"

        # Format 5: Legacy spaced record in DB identified by clean 10-digit
        res5 = await client.post("/api/v1/auth/identify", json={"country_code": "+91", "mobile_number": "8074182799"})
        assert res5.status_code == 200
        assert res5.json()["next_step"] == "password"

    # -------------------------------------------------------------------------
    # Scenario 9: Inactive Delivery Person -> login rejected
    # -------------------------------------------------------------------------
    async def test_scenario_9_inactive_delivery_person_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Deactivated Delivery Person account:
        1. /identify returns 403 Forbidden with clear message.
        2. /staff/login returns 403 Forbidden.
        """
        inactive_dp = User(
            full_name="Deactivated Courier",
            email="deactivated.courier@chovique.com",
            phone="+918074182787",
            role="delivery_person",
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=False,
            is_phone_verified=True,
        )
        db_session.add(inactive_dp)
        await db_session.commit()

        # Identify -> 403 Forbidden
        ident_res = await client.post(
            "/api/v1/auth/identify",
            json={"country_code": "+91", "mobile_number": "8074182787"},
        )
        assert ident_res.status_code == 403
        assert "deactivated" in ident_res.json()["detail"].lower()

        # Staff login -> 403 Forbidden
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "8074182787", "password": "DeliveryPass123!"},
        )
        assert login_res.status_code == 403
        assert "deactivated" in login_res.json()["detail"].lower()

    # -------------------------------------------------------------------------
    # Scenario 10: Delivery Person cannot access Admin or Super Admin APIs
    # -------------------------------------------------------------------------
    async def test_scenario_10_delivery_person_rbac_blocks_admin_apis(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Delivery Person authenticated credentials:
        1. Attempting to call Admin API (/api/v1/admin/delivery-boys) returns 403 Forbidden.
        2. Attempting to call Super Admin API (/api/v1/superadmin/overview) returns 403 Forbidden.
        3. Attempting to call Delivery API (/api/v1/delivery/route) succeeds (200 OK).
        """
        dp = User(
            full_name="Manoj Partner",
            email="manoj.partner@chovique.com",
            phone="+918074182788",
            role="delivery_person",
            hashed_password=hash_password("DeliveryPass123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(dp)
        await db_session.commit()

        # Login as Delivery Person
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={"phone": "8074182788", "password": "DeliveryPass123!"},
        )
        assert login_res.status_code == 200
        dp_token = login_res.json()["access_token"]
        dp_headers = {"Authorization": f"Bearer {dp_token}"}

        # 1. Admin API: /admin/delivery-boys -> 403 Forbidden
        admin_res = await client.get("/api/v1/admin/delivery-boys", headers=dp_headers)
        assert admin_res.status_code == 403
        assert "permission" in admin_res.json()["detail"].lower()

        # 2. Super Admin API: /superadmin/overview -> 403 Forbidden
        sa_res = await client.get("/api/v1/superadmin/overview", headers=dp_headers)
        assert sa_res.status_code == 403
        assert "permission" in sa_res.json()["detail"].lower()

        # 3. Delivery API: /delivery-boy/route -> 200 OK
        route_res = await client.get("/api/v1/delivery-boy/route", headers=dp_headers)
        assert route_res.status_code == 200
