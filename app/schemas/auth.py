from pydantic import BaseModel, EmailStr, Field, field_validator
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


# ==========================================================
# Register
# ==========================================================

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        trimmed = v.strip() if v else ""
        if not trimmed or len(trimmed) < 2:
            raise ValueError("Full Name must be at least 2 characters.")
        if not re.search(r"[a-zA-Z]", trimmed):
            raise ValueError("Full Name must contain valid letters.")
        return trimmed

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ==========================================================
# Verify Registration OTP
# ==========================================================

class VerifyOTPRequest(BaseModel):
    email: EmailStr
    otp: str
    full_name: str = Field(..., min_length=2, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        return validate_otp_format(v)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


VerifyRegistrationOTPRequest = VerifyOTPRequest


# ==========================================================
# Login
# ==========================================================

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password is required.")
        return v


# ==========================================================
# Google Login
# ==========================================================

class GoogleLoginRequest(BaseModel):
    id_token: str

    @field_validator("id_token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Google ID Token is required.")
        return v.strip()


# ==========================================================
# Set Password
# ==========================================================

class SetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8)
    confirm_password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        return validate_password_strength(v)


# ==========================================================
# Forgot Password
# ==========================================================

class ForgotPasswordRequest(BaseModel):
    email: EmailStr


# ==========================================================
# Resend Registration OTP
# ==========================================================

class ResendOTPRequest(BaseModel):
    email: EmailStr


# ==========================================================
# Resend Forgot Password OTP
# ==========================================================

class ResendForgotOTPRequest(BaseModel):
    email: EmailStr

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
    email: EmailStr
    otp: str
    password: str = Field(..., min_length=8)
    confirm_password: str

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

class OTPSentResponse(BaseModel):
    """Response for register / resend-otp (no user object yet)."""
    message: str
    email: EmailStr
    expires_in: int


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