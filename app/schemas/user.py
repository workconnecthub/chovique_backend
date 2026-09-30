from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator
import re


# ==========================================================
# Profile Update Payload
# ==========================================================

class ProfileUpdatePayload(BaseModel):
    name: Optional[str] = None
    full_name: Optional[str] = None
    phone: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    preferences: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None

    @field_validator("full_name", "name", mode="before")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            s = str(v).strip()
            if not s:
                raise ValueError("Full Name cannot be empty.")
            if len(s) < 2 or len(s) > 100:
                raise ValueError("Full Name must be between 2 and 100 characters.")
            if not any(c.isalpha() for c in s):
                raise ValueError("Full Name must contain letters.")
            return s
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v):
        if v is not None and str(v).strip():
            s = str(v).strip()
            cleaned = re.sub(r"\D", "", s)
            if cleaned.startswith("91") and len(cleaned) == 12:
                cleaned = cleaned[2:]
            elif cleaned.startswith("0") and len(cleaned) == 11:
                cleaned = cleaned[1:]
            if not re.match(r"^[6-9]\d{9}$", cleaned):
                raise ValueError("Phone number must be a valid 10-digit Indian number starting with 6, 7, 8, or 9.")
            return cleaned
        return v



# ==========================================================
# Nested Address + Profile (mirrors frontend UserProfile type)
# ==========================================================

class AddressSchema(BaseModel):
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""


class UserProfileSchema(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""
    avatar: str = ""
    avatarUrl: Optional[str] = None
    dob: Optional[str] = None
    gender: Optional[str] = None
    preferences: Optional[str] = None
    address: AddressSchema


# ==========================================================
# User Response — nested shape matching frontend User type
# { id, name, email, role, profile: { name, email, phone, avatar,
#   avatarUrl, dob, gender, preferences, address: { street, city, state, zip } } }
# ==========================================================

class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    profile: UserProfileSchema
    avatar_url: Optional[str] = None
    avatar: Optional[str] = None

    # Additional status fields (optional usage on frontend)
    is_email_verified: bool = False
    is_active: bool = True
    has_password: bool = True

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_user(cls, user):
        user_dict = getattr(user, "__dict__", {})

        full_name = user_dict.get("full_name") or getattr(user, "full_name", "") or ""
        email = user_dict.get("email") or getattr(user, "email", "") or ""
        role = user_dict.get("role") or getattr(user, "role", "customer") or "customer"
        user_id = str(user_dict.get("id") or getattr(user, "id", ""))
        phone = user_dict.get("phone") or getattr(user, "phone", "") or ""
        dob = user_dict.get("dob") or getattr(user, "dob", None)
        gender = user_dict.get("gender") or getattr(user, "gender", None)
        is_email_verified = user_dict.get("is_email_verified", getattr(user, "is_email_verified", True))
        is_active = user_dict.get("is_active", getattr(user, "is_active", True))
        has_password = bool(user_dict.get("hashed_password") or getattr(user, "hashed_password", None))

        avatar_url = user_dict.get("avatar_url")
        if avatar_url is None:
            try:
                avatar_url = user.avatar_url
            except Exception:
                avatar_url = None

        if avatar_url and "storageapi.dev" in avatar_url:
            clean_key = avatar_url.split("storageapi.dev/")[-1].lstrip("/")
            avatar_url = f"/api/v1/media/{clean_key}"

        initials = ""
        if full_name:
            initials = "".join(p[0].upper() for p in full_name.split()[:2])

        return cls(
            id=user_id,
            name=full_name,
            email=email,
            role=role,
            avatar_url=avatar_url,
            avatar=initials,
            profile=UserProfileSchema(
                name=full_name,
                email=email,
                phone=phone,
                avatar=initials,
                avatarUrl=avatar_url,
                dob=dob.strftime("%Y-%m-%d") if dob else None,
                gender=gender,
                preferences=None,
                address=AddressSchema(),
            ),
            is_email_verified=is_email_verified,
            is_active=is_active,
            has_password=has_password,
        )


# ==========================================================
# System User Response for /admin/users
# Mirrors frontend SystemUser type (with permissions object)
# ==========================================================

class PermissionsSchema(BaseModel):
    viewAnalytics: bool = False
    manageUsers: bool = False
    configureThemes: bool = False
    exportData: bool = False


class SystemUserResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    avatar_url: Optional[str] = None
    avatar: Optional[str] = None
    permissions: PermissionsSchema

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_user(cls, user) -> "SystemUserResponse":
        role = user.role
        # Derive permissions from role
        is_superadmin = (role == "superadmin")
        is_admin = (role in ("admin", "superadmin"))
        initials = "".join(p[0].upper() for p in (user.full_name or "").split()[:2])
        raw_avatar = getattr(user, "avatar_url", None)
        if raw_avatar and "storageapi.dev" in raw_avatar:
            clean_key = raw_avatar.split("storageapi.dev/")[-1].lstrip("/")
            raw_avatar = f"/api/v1/media/{clean_key}"
        return cls(
            id=str(user.id),
            name=user.full_name or "",
            email=user.email or "",
            role=role,
            avatar_url=raw_avatar,
            avatar=initials,
            permissions=PermissionsSchema(
                viewAnalytics=is_admin,
                manageUsers=is_superadmin,
                configureThemes=is_superadmin,
                exportData=is_admin,
            ),
        )


# ==========================================================
# Avatar Upload Response
# ==========================================================

class AvatarUploadResponse(BaseModel):
    avatar_url: str


# ==========================================================
# Customer Address Schemas
# ==========================================================

class CustomerAddressCreate(BaseModel):
    title: str = "Home"
    name: str
    house_number: Optional[str] = None
    street: str
    area: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    district: Optional[str] = None
    state: str
    zip: str
    phone: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    location_source: Optional[str] = "MANUAL"
    location_verified: Optional[bool] = False
    isDefault: bool = False

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        s = str(v or "").strip()
        if not s:
            raise ValueError("Address Label is required.")
        if len(s) < 2 or len(s) > 30:
            raise ValueError("Address Label must be between 2 and 30 characters.")
        if not any(c.isalnum() for c in s):
            raise ValueError("Address Label cannot contain only special characters.")
        return s

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v):
        s = str(v or "").strip()
        if not s:
            raise ValueError("Recipient Full Name is required.")
        if len(s) < 2 or len(s) > 100:
            raise ValueError("Recipient Full Name must be between 2 and 100 characters.")
        if not any(c.isalpha() for c in s):
            raise ValueError("Recipient Full Name must contain valid letters.")
        return s

    @field_validator("street", mode="before")
    @classmethod
    def validate_street(cls, v):
        s = str(v or "").strip()
        if not s:
            raise ValueError("Street Address is required.")
        if len(s) > 250:
            raise ValueError("Street Address cannot exceed 250 characters.")
        return s

    @field_validator("city", mode="before")
    @classmethod
    def validate_city(cls, v):
        s = str(v or "").strip()
        if not s:
            raise ValueError("City is required.")
        if len(s) < 2 or len(s) > 100:
            raise ValueError("City must be between 2 and 100 characters.")
        if s.isdigit():
            raise ValueError("City cannot be numbers-only.")
        return s

    @field_validator("state", mode="before")
    @classmethod
    def validate_state(cls, v):
        s = str(v or "").strip()
        if not s:
            raise ValueError("State is required.")
        return s

    @field_validator("zip", mode="before")
    @classmethod
    def validate_zip(cls, v):
        s = str(v or "").strip()
        if not re.match(r"^\d{6}$", s):
            raise ValueError("PIN/Postal Code must be exactly 6 digits.")
        return s

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v):
        s = str(v or "").strip()
        cleaned = re.sub(r"\D", "", s)
        if cleaned.startswith("91") and len(cleaned) == 12:
            cleaned = cleaned[2:]
        elif cleaned.startswith("0") and len(cleaned) == 11:
            cleaned = cleaned[1:]
        if not re.match(r"^[6-9]\d{9}$", cleaned):
            raise ValueError("Phone number must be a valid 10-digit Indian number starting with 6, 7, 8, or 9.")
        return cleaned


class CustomerAddressUpdate(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    house_number: Optional[str] = None
    street: Optional[str] = None
    area: Optional[str] = None
    landmark: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    phone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    location_source: Optional[str] = None
    location_verified: Optional[bool] = None
    isDefault: Optional[bool] = None

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, v):
        if v is not None:
            s = str(v).strip()
            if not s:
                raise ValueError("Address Label cannot be empty.")
            if len(s) < 2 or len(s) > 30:
                raise ValueError("Address Label must be between 2 and 30 characters.")
            if not any(c.isalnum() for c in s):
                raise ValueError("Address Label cannot contain only special characters.")
            return s
        return v

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            s = str(v).strip()
            if not s:
                raise ValueError("Recipient Full Name cannot be empty.")
            if len(s) < 2 or len(s) > 100:
                raise ValueError("Recipient Full Name must be between 2 and 100 characters.")
            if not any(c.isalpha() for c in s):
                raise ValueError("Recipient Full Name must contain valid letters.")
            return s
        return v

    @field_validator("street", mode="before")
    @classmethod
    def validate_street(cls, v):
        if v is not None:
            s = str(v).strip()
            if not s:
                raise ValueError("Street Address cannot be empty.")
            if len(s) > 250:
                raise ValueError("Street Address cannot exceed 250 characters.")
            return s
        return v

    @field_validator("city", mode="before")
    @classmethod
    def validate_city(cls, v):
        if v is not None:
            s = str(v).strip()
            if not s:
                raise ValueError("City cannot be empty.")
            if len(s) < 2 or len(s) > 100:
                raise ValueError("City must be between 2 and 100 characters.")
            if s.isdigit():
                raise ValueError("City cannot be numbers-only.")
            return s
        return v

    @field_validator("zip", mode="before")
    @classmethod
    def validate_zip(cls, v):
        if v is not None and str(v).strip():
            s = str(v).strip()
            if not re.match(r"^\d{6}$", s):
                raise ValueError("PIN/Postal Code must be exactly 6 digits.")
            return s
        return v

    @field_validator("phone", mode="before")
    @classmethod
    def validate_phone(cls, v):
        if v is not None and str(v).strip():
            s = str(v).strip()
            cleaned = re.sub(r"\D", "", s)
            if cleaned.startswith("91") and len(cleaned) == 12:
                cleaned = cleaned[2:]
            elif cleaned.startswith("0") and len(cleaned) == 11:
                cleaned = cleaned[1:]
            if not re.match(r"^[6-9]\d{9}$", cleaned):
                raise ValueError("Phone number must be a valid 10-digit Indian number starting with 6, 7, 8, or 9.")
            return cleaned
        return v


class CustomerAddressResponse(BaseModel):
    id: str
    title: str
    name: str
    house_number: Optional[str] = None
    street: str
    area: Optional[str] = None
    landmark: Optional[str] = None
    city: str
    district: Optional[str] = None
    state: str
    zip: str
    phone: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    location_source: Optional[str] = "MANUAL"
    location_verified: Optional[bool] = False
    isDefault: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)



# ==========================================================
# Notification Response
# ==========================================================

class SupportNotificationResponse(BaseModel):
    id: str
    title: Optional[str] = None
    message: Optional[str] = None
    text: str
    date: str
    read: bool
    is_read: Optional[bool] = None
    type: str = "general"
    referenceId: Optional[str] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)