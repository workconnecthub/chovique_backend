import re
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, validator


def validate_indian_phone(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    from app.integrations.msg91 import normalize_phone
    try:
        return normalize_phone(v, default_country_code="+91")
    except Exception:
        raise ValueError("Invalid Indian phone number. Must be a 10-digit number starting with 6, 7, 8, or 9.")


def validate_strong_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", v):
        raise ValueError("Password must contain at least one uppercase letter (A-Z).")
    if not re.search(r"[a-z]", v):
        raise ValueError("Password must contain at least one lowercase letter (a-z).")
    if not re.search(r"[0-9]", v):
        raise ValueError("Password must contain at least one number (0-9).")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", v):
        raise ValueError("Password must contain at least one special character (!@#$%^&* etc.).")
    return v


class AdminCreateRequest(BaseModel):
    """Schema for registering a new administrator."""
    full_name: str = Field(..., min_length=2, max_length=120, description="Full Name")
    email: EmailStr = Field(..., description="Email address")
    phone: Optional[str] = Field(None, description="Indian phone number")
    role: str = Field("admin", description="Role: 'admin' or 'superadmin'")
    password: str = Field(..., description="Strong password")
    confirm_password: str = Field(..., description="Password confirmation")
    status: str = Field("active", description="Status: 'active' or 'inactive'")

    @validator("phone")
    def check_phone(cls, v):
        return validate_indian_phone(v)

    @validator("password")
    def check_password(cls, v):
        return validate_strong_password(v)

    @validator("confirm_password")
    def check_match(cls, v, values):
        if "password" in values and v != values["password"]:
            raise ValueError("Password confirmation does not match password.")
        return v

    @validator("role")
    def check_role(cls, v):
        if v.lower() not in ["admin", "superadmin"]:
            raise ValueError("Role must be 'admin' or 'superadmin'.")
        return v.lower()

    @validator("status")
    def check_status(cls, v):
        if v.lower() not in ["active", "inactive"]:
            raise ValueError("Status must be 'active' or 'inactive'.")
        return v.lower()


class AdminUpdateRequest(BaseModel):
    """Schema for updating an existing administrator's profile."""
    full_name: Optional[str] = Field(None, min_length=2, max_length=120)
    email: Optional[EmailStr] = Field(None)
    phone: Optional[str] = Field(None)
    role: Optional[str] = Field(None)
    status: Optional[str] = Field(None)

    @validator("phone")
    def check_phone(cls, v):
        return validate_indian_phone(v)

    @validator("role")
    def check_role(cls, v):
        if v and v.lower() not in ["admin", "superadmin"]:
            raise ValueError("Role must be 'admin' or 'superadmin'.")
        return v.lower() if v else v

    @validator("status")
    def check_status(cls, v):
        if v and v.lower() not in ["active", "inactive"]:
            raise ValueError("Status must be 'active' or 'inactive'.")
        return v.lower() if v else v


class AdminStatusUpdateRequest(BaseModel):
    """Schema for updating admin status."""
    status: str = Field(..., description="'active' or 'inactive'")

    @validator("status")
    def check_status(cls, v):
        if v.lower() not in ["active", "inactive"]:
            raise ValueError("Status must be 'active' or 'inactive'.")
        return v.lower()


class AdminPasswordUpdateRequest(BaseModel):
    """Schema for securely updating admin password."""
    new_password: str = Field(..., description="New strong password")
    confirm_password: str = Field(..., description="Password confirmation")

    @validator("new_password")
    def check_password(cls, v):
        return validate_strong_password(v)

    @validator("confirm_password")
    def check_match(cls, v, values):
        if "new_password" in values and v != values["new_password"]:
            raise ValueError("Password confirmation does not match new password.")
        return v


class AdminUserResponse(BaseModel):
    """Response model for administrator details."""
    id: str
    full_name: str
    email: str
    phone: Optional[str] = None
    role: str
    is_active: bool
    status: str
    created_at: str
    last_login_at: Optional[str] = None


class AdminListResponse(BaseModel):
    """Paginated response for administrator list."""
    items: List[AdminUserResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    limit: int = 10
