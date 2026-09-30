import re
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FulfillmentType(str, Enum):
    LOCAL = "LOCAL"
    COURIER = "COURIER"
    PICKUP = "PICKUP"


class ShippingProviderType(str, Enum):
    INTERNAL = "INTERNAL"
    SHIPROCKET = "SHIPROCKET"
    DELHIVERY = "DELHIVERY"
    OTHER = "OTHER"


class DeliveryMode(str, Enum):
    LOCAL = "LOCAL"
    COURIER = "COURIER"
    UNAVAILABLE = "UNAVAILABLE"


class LocationSource(str, Enum):
    GOOGLE_PLACE = "GOOGLE_PLACE"
    CURRENT_LOCATION = "CURRENT_LOCATION"
    MANUAL = "MANUAL"
    SAVED_ADDRESS = "SAVED_ADDRESS"


# ─── Public Shipping Calculation ───────────────────────────────────────

class ShippingCalculateRequest(BaseModel):
    pincode: str
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    cart_total: Optional[float] = 0.0
    subtotal: Optional[float] = None

    def get_subtotal(self) -> float:
        if self.subtotal is not None:
            return float(self.subtotal)
        return float(self.cart_total or 0.0)

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        s = str(v or "").strip()
        if not re.match(r"^[1-9][0-9]{5}$", s):
            raise ValueError("PIN Code must be a valid 6-digit Indian postal code.")
        return s

    @field_validator("latitude", "longitude")
    @classmethod
    def validate_coordinates(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        # Verify valid geographic ranges if coordinates provided
        if not (-90.0 <= v <= 90.0):
            return None
        return v


class ShippingCalculateResponse(BaseModel):
    serviceable: bool
    is_serviceable: Optional[bool] = None
    fulfillment_type: str = "LOCAL"  # LOCAL, COURIER
    shipping_provider: str = "INTERNAL"  # INTERNAL, SHIPROCKET, etc.
    delivery_charge: float = 0.0
    free_delivery_applied: bool = False
    is_free_delivery: Optional[bool] = None
    service_area: Optional[str] = None
    estimated_delivery: str = "Within 3-5 hours"
    message: str = "Delivery available"
    origin_store: Optional[str] = None
    origin_store_id: Optional[str] = None

    def model_post_init(self, __context) -> None:
        if self.is_serviceable is None:
            self.is_serviceable = self.serviceable
        if self.is_free_delivery is None:
            self.is_free_delivery = self.free_delivery_applied



# ─── Store Location Schemas ────────────────────────────────────────────

class StoreLocationCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=120)
    house_number: Optional[str] = None
    street: str = Field(..., min_length=2, max_length=255)
    area: Optional[str] = None
    city: str = Field(default="Visakhapatnam", min_length=2, max_length=100)
    district: Optional[str] = None
    state: str = Field(default="Andhra Pradesh", min_length=2, max_length=100)
    pincode: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool = False
    active: bool = True

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        s = str(v or "").strip()
        if not re.match(r"^[1-9][0-9]{5}$", s):
            raise ValueError("PIN Code must be a valid 6-digit Indian postal code.")
        return s


class StoreLocationUpdate(BaseModel):
    name: Optional[str] = None
    house_number: Optional[str] = None
    street: Optional[str] = None
    area: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    phone: Optional[str] = None
    is_primary: Optional[bool] = None
    active: Optional[bool] = None

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = str(v).strip()
            if not re.match(r"^[1-9][0-9]{5}$", s):
                raise ValueError("PIN Code must be a valid 6-digit Indian postal code.")
            return s
        return v


class StoreLocationResponse(BaseModel):
    id: str
    name: str
    house_number: Optional[str] = None
    street: str
    area: Optional[str] = None
    city: str
    district: Optional[str] = None
    state: str
    pincode: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    phone: Optional[str] = None
    is_primary: bool
    active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ─── Delivery Service Area Schemas ─────────────────────────────────────

class DeliveryServiceAreaCreate(BaseModel):
    store_location_id: Optional[str] = None
    pincode: str
    city: str = "Visakhapatnam"
    district: Optional[str] = None
    state: str = "Andhra Pradesh"
    delivery_mode: str = "LOCAL"  # LOCAL, COURIER, UNAVAILABLE
    delivery_charge: float = 40.0
    free_delivery_threshold: Optional[float] = None
    same_day_available: bool = True
    estimated_delivery: str = "Within 3-5 hours (Same Day)"
    active: bool = True

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        s = str(v or "").strip()
        if not re.match(r"^[1-9][0-9]{5}$", s):
            raise ValueError("PIN Code must be a valid 6-digit Indian postal code.")
        return s

    @field_validator("delivery_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        s = str(v or "").upper().strip()
        if s not in ("LOCAL", "COURIER", "UNAVAILABLE"):
            raise ValueError("Delivery mode must be LOCAL, COURIER, or UNAVAILABLE.")
        return s


class DeliveryServiceAreaUpdate(BaseModel):
    store_location_id: Optional[str] = None
    pincode: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    delivery_mode: Optional[str] = None
    delivery_charge: Optional[float] = None
    free_delivery_threshold: Optional[float] = None
    same_day_available: Optional[bool] = None
    estimated_delivery: Optional[str] = None
    active: Optional[bool] = None

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = str(v).strip()
            if not re.match(r"^[1-9][0-9]{5}$", s):
                raise ValueError("PIN Code must be a valid 6-digit Indian postal code.")
            return s
        return v

    @field_validator("delivery_mode")
    @classmethod
    def validate_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            s = str(v).upper().strip()
            if s not in ("LOCAL", "COURIER", "UNAVAILABLE"):
                raise ValueError("Delivery mode must be LOCAL, COURIER, or UNAVAILABLE.")
            return s
        return v


class DeliveryServiceAreaResponse(BaseModel):
    id: str
    store_location_id: Optional[str] = None
    pincode: str
    city: str
    district: Optional[str] = None
    state: str
    delivery_mode: str
    delivery_charge: float
    free_delivery_threshold: Optional[float] = None
    same_day_available: bool
    estimated_delivery: str
    active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
