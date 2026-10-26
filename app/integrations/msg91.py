import logging
import re
from typing import Optional, Tuple
import httpx
import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberType

from app.core.config import settings
from app.core.exceptions import AppError

logger = logging.getLogger(__name__)


class OTPDeliveryError(AppError):
    def __init__(self, message: str = "Unable to deliver OTP at this time. Please try again."):
        super().__init__(message=message)


def parse_and_normalize_phone(
    phone: str,
    default_country_code: Optional[str] = "+91",
) -> Tuple[str, str, str]:
    """
    Safely parse and normalize mobile numbers using phonenumbers library.
    Returns: (e164_phone, national_phone, country_code_str)
    Example: ('+918074182784', '8074182784', '+91')
    """
    if not phone or not str(phone).strip():
        raise ValueError("Mobile number is required.")

    raw = str(phone).strip()

    # Normalize default country code prefix
    cc = (str(default_country_code).strip() if default_country_code else "+91")
    if not cc.startswith("+"):
        cc = "+" + cc
    cc_digits = cc.lstrip("+")

    # If raw already has a leading '+', parse directly
    if raw.startswith("+"):
        try:
            parsed = phonenumbers.parse(raw, None)
        except Exception as e:
            raise ValueError(f"Invalid phone number format: {e}")
    else:
        digits = re.sub(r"\D", "", raw)
        if not digits:
            raise ValueError("Mobile number must contain digits.")

        # If number is > 10 digits and starts with the country code digits (e.g. 918074182784)
        if len(digits) > 10 and digits.startswith(cc_digits):
            full = "+" + digits
        else:
            # Handle trunk prefix 0 (e.g. 08074182784 -> 8074182784)
            if digits.startswith("0") and len(digits) == 11:
                digits = digits[1:]
            full = f"{cc}{digits}"

        try:
            parsed = phonenumbers.parse(full, None)
        except Exception as e:
            raise ValueError(f"Invalid phone number format: {e}")

    if not phonenumbers.is_possible_number(parsed) or not phonenumbers.is_valid_number(parsed):
        raise ValueError("Please provide a valid mobile number.")

    # Additional national validation for India (+91)
    if parsed.country_code == 91:
        national = str(parsed.national_number)
        if len(national) != 10 or national[0] not in "6789":
            raise ValueError("Please provide a valid 10-digit mobile number starting with 6, 7, 8, or 9.")

    e164 = phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
    national = str(parsed.national_number)
    country_code_str = f"+{parsed.country_code}"
    return e164, national, country_code_str


def normalize_phone(phone: str, default_country_code: Optional[str] = "+91") -> str:
    """
    Normalize phone number into canonical E.164 format (e.g. +918074182784).
    """
    e164, _, _ = parse_and_normalize_phone(phone, default_country_code)
    return e164


def mask_phone_number(phone: str, default_country_code: Optional[str] = "+91") -> str:
    """
    Mask phone number for safe logging (e.g. +91 80*** ***84).
    Guarantees that the country code is correctly separated and the national number
    digits are never misinterpreted as a country code.
    """
    if not phone:
        return "***"
    try:
        _, nat, cc = parse_and_normalize_phone(phone, default_country_code)
        if len(nat) >= 6:
            return f"{cc} {nat[:2]}*** ***{nat[-2:]}"
        return f"{cc} ***"
    except Exception:
        digits = re.sub(r"\D", "", str(phone))
        if len(digits) >= 10:
            return f"+91 {digits[:2]}*** ***{digits[-2:]}"
        return "***"


def to_msg91_recipient(phone: str, default_country_code: Optional[str] = "+91") -> str:
    """Format phone number for MSG91 (requires country code digits without plus, e.g. 918074182784)."""
    e164, _, _ = parse_and_normalize_phone(phone, default_country_code)
    return e164.lstrip("+")


class MSG91Client:
    """
    MSG91 OTP API Client.
    Supports asynchronous OTP dispatch with timeout and error handling.
    Falls back safely to simulated mode when no auth key is configured or during automated testing.
    """

    def __init__(
        self,
        auth_key: Optional[str] = None,
        template_id: Optional[str] = None,
        sender_id: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        self.auth_key = (auth_key or settings.MSG91_AUTH_KEY).strip()
        self.template_id = (template_id or settings.MSG91_OTP_TEMPLATE_ID).strip()
        self.sender_id = (sender_id or settings.MSG91_SENDER_ID).strip()
        self.api_url = (api_url or settings.MSG91_API_URL).strip() or "https://control.msg91.com/api/v5/otp"

    @property
    def is_configured(self) -> bool:
        return bool(self.auth_key and not self.auth_key.startswith("your_"))

    async def send_otp(
        self,
        phone: str,
        otp: str,
        template_id: Optional[str] = None,
    ) -> bool:
        """
        Deliver OTP via MSG91 OTP API.
        Never logs or exposes the OTP in error messages or logs.
        """
        masked = mask_phone_number(phone)
        recipient = to_msg91_recipient(phone)
        tmpl = (template_id or self.template_id).strip()

        if not self.is_configured:
            logger.info("MSG91 mock delivery active: OTP dispatched to masked number %s", masked)
            return True

        headers = {
            "authkey": self.auth_key,
            "Content-Type": "application/json",
        }

        params = {
            "template_id": tmpl,
            "mobile": recipient,
            "otp": otp,
            "otp_expiry": settings.MSG91_OTP_EXPIRY_MINUTES,
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    params=params,
                )

                if response.status_code >= 400:
                    logger.error(
                        "MSG91 HTTP error: status=%d for recipient=%s",
                        response.status_code,
                        masked,
                    )
                    raise OTPDeliveryError("Failed to deliver OTP via SMS provider. Please try again.")

                try:
                    data = response.json()
                except Exception:
                    data = {}

                # MSG91 returns type="error" on invalid template, balance, or key
                if isinstance(data, dict) and data.get("type") == "error":
                    msg = data.get("message", "Provider returned an error.")
                    logger.error("MSG91 provider error for recipient=%s: %s", masked, msg)
                    raise OTPDeliveryError(f"SMS Provider Error: {msg}")

                logger.info("MSG91 OTP delivered successfully to %s", masked)
                return True

        except httpx.TimeoutException:
            logger.error("MSG91 request timed out for %s", masked)
            raise OTPDeliveryError("SMS provider timed out. Please try again in a few moments.")
        except httpx.RequestError as e:
            logger.error("MSG91 network request error for %s: %s", masked, type(e).__name__)
            raise OTPDeliveryError("Failed to communicate with SMS delivery service. Please try again.")


msg91_client = MSG91Client()
