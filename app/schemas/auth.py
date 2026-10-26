from typing import Optional, Any
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
import re

from app.schemas.user import UserResponse


# ==========================================================
# Password Policy Constant
# ==========================================================

PASSWORD_POLICY_ERROR = (
    "Password must be at least 8 characters and include at least one uppercase letter, "
    "one lowercase letter, one number, and one special character."
)


def validate_password_strength(v: str) -> str:
    """Helper to validate password strength across request schemas."""
    if not v:
        raise ValueError("Password is required.")
    if (
        len(v) < 8
        or not re.search(r"[A-Z]", v)
        or not re.search(r"[a-z]", v)
        or not re.search(r"[0-9]", v)
        or not re.search(r"[^A-Za-z0-9]", v)
    ):
        raise ValueError(PASSWORD_POLICY_ERROR)
    return v


def validate_otp_format(v: str) -> str:
    """Helper to validate 6-digit numeric OTP format."""
    v_clean = v.strip() if v else ""
    if not v_clean:
        raise ValueError("OTP is required.")
    if not re.match(r"^\d{6}$", v_clean):
        raise ValueError("OTP must be a valid 6-digit numeric code.")
    return v_clean


def validate_phone_number(v: str, country_code: Optional[str] = "+91") -> str:
    """Helper to validate and normalize phone numbers into canonical E.164 format (+918074182784)."""
    if not v or not str(v).strip():
        raise ValueError("Phone number is required.")
    from app.integrations.msg91 import normalize_phone
    return normalize_phone(str(v).strip(), default_country_code=country_code)


def normalize_staff_role(role_val: str) -> str:
    """Normalize role string to canonical backend role."""
    r = (role_val or "").lower().strip()
    if r in ("super_admin", "superadmin"):
        return "superadmin"
    if r in ("delivery_person", "delivery_boy"):
        return "delivery_person"
    if r == "admin":
        return "admin"
    raise ValueError("Role must be one of: super_admin, admin, delivery_person.")




# ==========================================================
# Forgot Password
# ==========================================================

class ForgotPasswordRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_phone_number(v)
        return None




# ==========================================================
# Resend Forgot Password OTP
# ==========================================================

class ResendForgotOTPRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_phone_number(v)
        return None

# ==========================================================
# Update Password (Authenticated OTP Flow)
# ==========================================================

class UpdatePasswordSendOTPRequest(BaseModel):
    email: EmailStr

class UpdatePasswordVerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        return validate_otp_format(v)

class UpdatePasswordRequest(BaseModel):
    email: EmailStr
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ==========================================================
# Reset Password
# ==========================================================

class ResetPasswordRequest(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    otp: str
    password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_phone_number(v)
        return None

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        return validate_otp_format(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ==========================================================
# Change Password
# ==========================================================

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("current_password")
    @classmethod
    def validate_current(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Current password is required.")
        return v

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ==========================================================
# Response Wrappers
# ==========================================================



from typing import Optional

class AuthUserResponse(BaseModel):
    """Response for endpoints that return a token pair + user profile."""
    message: str
    user: UserResponse
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    refresh_token: Optional[str] = None


class RefreshTokenResponse(BaseModel):
    message: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None


class ForgotPasswordResponse(BaseModel):
    message: str
    expires_in: int = 300


# ==========================================================
# Customer Mobile OTP Schemas
# ==========================================================

class CustomerSendOTPRequest(BaseModel):
    phone: Optional[str] = None
    mobile_number: Optional[str] = None
    country_code: Optional[str] = "+91"

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("phone") or data.get("mobile_number")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import normalize_phone
            norm = normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["phone"] = norm
            data["mobile_number"] = norm
            data["country_code"] = str(cc).strip()
        return data


class CustomerSendOTPResponse(BaseModel):
    message: str
    phone: str
    country_code: Optional[str] = "+91"
    mobile_number: Optional[str] = None
    expires_in: int = 300
    cooldown_seconds: int = 60


class CustomerResendOTPRequest(BaseModel):
    phone: Optional[str] = None
    mobile_number: Optional[str] = None
    country_code: Optional[str] = "+91"

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("phone") or data.get("mobile_number")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import normalize_phone
            norm = normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["phone"] = norm
            data["mobile_number"] = norm
            data["country_code"] = str(cc).strip()
        return data


class CustomerVerifyOTPRequest(BaseModel):
    phone: Optional[str] = None
    mobile_number: Optional[str] = None
    country_code: Optional[str] = "+91"
    otp: str

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("phone") or data.get("mobile_number")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import normalize_phone
            norm = normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["phone"] = norm
            data["mobile_number"] = norm
            data["country_code"] = str(cc).strip()
        return data

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        return validate_otp_format(v)


# ==========================================================
# Staff Authentication Schemas
# ==========================================================
# Single Unified Login: Identify Mobile Number
# ==========================================================

class IdentifyRequest(BaseModel):
    country_code: Optional[str] = Field(default="+91", description="Country calling code, e.g. +91")
    mobile_number: Optional[str] = None
    phone: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def check_mobile_or_phone(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("mobile_number") or data.get("phone")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import parse_and_normalize_phone
            e164, national, cc_norm = parse_and_normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["country_code"] = cc_norm
            data["mobile_number"] = e164
            data["phone"] = e164
        return data


class IdentifyResponse(BaseModel):
    next_step: str  # "otp" or "password"
    message: str
    phone: Optional[str] = None
    country_code: Optional[str] = "+91"
    mobile_number: Optional[str] = None
    expires_in: Optional[int] = None
    resend_cooldown: Optional[int] = None
    remaining_daily_requests: Optional[int] = None


class StaffCheckMobileRequest(BaseModel):
    phone: Optional[str] = None
    mobile_number: Optional[str] = None
    country_code: Optional[str] = "+91"
    role: str

    @model_validator(mode="before")
    @classmethod
    def normalize_phone_field(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("phone") or data.get("mobile_number")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import normalize_phone
            norm = normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["phone"] = norm
            data["mobile_number"] = norm
            data["country_code"] = str(cc).strip()
        return data

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        return normalize_staff_role(v)


class StaffCheckMobileResponse(BaseModel):
    status: str = "ok"
    exists: bool = True
    role: str
    message: str = "Mobile number verified. Please enter your password to continue."


class StaffLoginRequest(BaseModel):
    phone: Optional[str] = None
    mobile_number: Optional[str] = None
    country_code: Optional[str] = "+91"
    password: str
    role: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def check_phone_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            cc = data.get("country_code") or "+91"
            val = data.get("phone") or data.get("mobile_number")
            if not val or not str(val).strip():
                raise ValueError("Mobile number is required.")
            from app.integrations.msg91 import normalize_phone
            norm = normalize_phone(str(val).strip(), default_country_code=str(cc).strip())
            data["phone"] = norm
            data["mobile_number"] = norm
            data["country_code"] = str(cc).strip()
        return data

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return normalize_staff_role(v)
        return None

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password is required.")
        return v


class StaffForgotPasswordRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and str(v).strip():
            return validate_phone_number(v)
        return None