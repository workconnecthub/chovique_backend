"""
Tests for Mobile Number and Country Code Handling across API, services, and utilities.
Validates E.164 normalization, international format resilience, masked logging,
PostgreSQL customer and staff lookups, and OTP rate-limiting.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.integrations.msg91 import (
    parse_and_normalize_phone,
    normalize_phone,
    mask_phone_number,
    to_msg91_recipient,
)
from app.models.user import User


# ==========================================================
# 1. UNIT TESTS: Normalization & Masking Utility
# ==========================================================

def test_parse_and_normalize_standard_indian_mobile():
    """Country code +91, mobile 8074182784 -> +918074182784."""
    e164, national, cc = parse_and_normalize_phone("8074182784", "+91")
    assert e164 == "+918074182784"
    assert national == "8074182784"
    assert cc == "+91"


def test_parse_and_normalize_with_spaces_and_formatting():
    """Country code and mobile number with spaces and dashes."""
    e164, national, cc = parse_and_normalize_phone(" 80 74 182-784 ", " +91 ")
    assert e164 == "+918074182784"
    assert national == "8074182784"
    assert cc == "+91"


def test_parse_and_normalize_already_international():
    """Number already supplied in international format should not prepend country code twice."""
    e164, national, cc = parse_and_normalize_phone("+918074182784", "+91")
    assert e164 == "+918074182784"
    assert national == "8074182784"
    assert cc == "+91"

    # Also without '+' but with 12 digits (918074182784)
    e164_alt, national_alt, _ = parse_and_normalize_phone("918074182784", "+91")
    assert e164_alt == "+918074182784"
    assert national_alt == "8074182784"


def test_parse_and_normalize_national_starting_with_91():
    """A 10-digit Indian number starting with 91 (e.g. 9198765432) must not treat 91 as country code."""
    e164, national, cc = parse_and_normalize_phone("9198765432", "+91")
    assert e164 == "+919198765432"
    assert national == "9198765432"
    assert cc == "+91"


def test_parse_and_normalize_leading_zero():
    """Trunk prefix 0 (e.g. 08074182784) is safely stripped."""
    e164, national, cc = parse_and_normalize_phone("08074182784", "+91")
    assert e164 == "+918074182784"
    assert national == "8074182784"


def test_parse_and_normalize_invalid_numbers():
    """Invalid, incomplete, or alphabetical numbers raise clear ValueError."""
    for invalid in ["12345", "0000000000", "invalid_phone", "", "   "]:
        with pytest.raises(ValueError):
            parse_and_normalize_phone(invalid, "+91")


def test_masked_phone_number_format():
    """
    Ensure the masked logs display the correct country code and masked national number (+91 80*** ***84)
    and do NOT misinterpret the first two digits '80' of the national number as '+80'.
    """
    assert mask_phone_number("8074182784", "+91") == "+91 80*** ***84"
    assert mask_phone_number("+918074182784") == "+91 80*** ***84"
    assert mask_phone_number(" 80 74 182 784 ", "+91") == "+91 80*** ***84"

    # MSG91 recipient format (country code digits + national digits without plus)
    assert to_msg91_recipient("8074182784", "+91") == "918074182784"
    assert to_msg91_recipient("+918074182784") == "918074182784"


# ==========================================================
# 2. INTEGRATION TESTS: POST /api/v1/auth/identify
# ==========================================================

@pytest.mark.asyncio
class TestPhoneHandlingAPI:
    """Test API endpoint payload handling, schema validation, and normalization."""

    async def test_identify_with_separate_country_code_and_mobile(self, client: AsyncClient, mock_redis):
        """API accepts country_code and mobile_number as separate fields."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": "8074182784",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "otp"
        assert data["phone"] == "+918074182784"
        assert data["country_code"] == "+91"
        assert data["mobile_number"] == "8074182784"

    async def test_identify_with_spaces_in_mobile(self, client: AsyncClient, mock_redis):
        """API handles whitespace and formatting characters in mobile number."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": " 80 74 182 784 ",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["phone"] == "+918074182784"
        assert data["next_step"] == "otp"

    async def test_identify_with_international_format(self, client: AsyncClient, mock_redis):
        """API handles already-international format without double-prepending."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": "+918074182784",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["phone"] == "+918074182784"

    async def test_identify_with_invalid_numbers_fails_422(self, client: AsyncClient):
        """Incomplete or invalid phone numbers return 422 Unprocessable Entity."""
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": "12345",
            },
        )
        assert res.status_code == 422

    async def test_identify_existing_legacy_customer_lookup(
        self, client: AsyncClient, db_session: AsyncSession, mock_redis
    ):
        """
        PostgreSQL lookup seamlessly finds existing customer records stored
        with legacy 10-digit format without requiring manual DB updates.
        """
        legacy_phone = "9876543210"
        cust = User(
            full_name="Legacy Customer",
            phone=legacy_phone,
            role="customer",
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(cust)
        await db_session.commit()

        # Identify with country_code '+91' and 10-digit mobile
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": legacy_phone,
            },
        )
        assert res.status_code == 200
        assert res.json()["next_step"] == "otp"

        # Verify OTP works for this customer
        otp = await mock_redis.get(f"otp:test_val:customer_login:{legacy_phone}")
        if not otp:
            otp = await mock_redis.get(f"otp:test_val:customer_login:+91{legacy_phone}")
        assert otp is not None

        verify_res = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"country_code": "+91", "phone": legacy_phone, "otp": otp},
        )
        assert verify_res.status_code == 200
        user_data = verify_res.json()["user"]
        phone_in_res = user_data.get("profile", {}).get("phone") or user_data.get("phone")
        assert phone_in_res in (legacy_phone, f"+91{legacy_phone}")

    async def test_identify_and_login_staff_lookup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """
        Staff account stored with 10-digit number is recognized during identify and staff login.
        """
        staff_phone = "9999900010"
        staff = User(
            full_name="Store Superadmin",
            email="superadmin10@chovique.com",
            phone=staff_phone,
            role="superadmin",
            hashed_password=hash_password("SuperSecret123!"),
            is_active=True,
            is_phone_verified=True,
        )
        db_session.add(staff)
        await db_session.commit()

        # 1. Identify step returns next_step='password'
        res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": staff_phone,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["next_step"] == "password"

        # 2. Staff Login with password succeeds
        login_res = await client.post(
            "/api/v1/auth/staff/login",
            json={
                "country_code": "+91",
                "mobile_number": staff_phone,
                "password": "SuperSecret123!",
                "role": "super_admin",
            },
        )
        assert login_res.status_code == 200
        assert login_res.json()["user"]["role"] == "superadmin"

    async def test_otp_delivery_and_daily_limit_enforcement(
        self, client: AsyncClient, mock_redis
    ):
        """
        Test that daily OTP quota (5 attempts/day) is accurately tracked and enforced
        using the normalized E.164 identifier.
        """
        phone = "8074182784"
        # First 5 calls: should decrease remaining_daily_requests from 4 down to 0
        for i in range(5):
            # Clear redis cooldown between iterations to test daily limit specifically
            await mock_redis.flushall()
            res = await client.post(
                "/api/v1/auth/identify",
                json={
                    "country_code": "+91",
                    "mobile_number": phone,
                },
            )
            assert res.status_code == 200
            assert res.json()["remaining_daily_requests"] == (4 - i)

        # 6th call: Daily quota exceeded -> 429
        await mock_redis.flushall()
        blocked_res = await client.post(
            "/api/v1/auth/identify",
            json={
                "country_code": "+91",
                "mobile_number": phone,
            },
        )
        assert blocked_res.status_code == 429
        detail = blocked_res.json()["detail"].lower()
        assert "daily" in detail and "limit" in detail
