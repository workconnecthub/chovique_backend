from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field

ALLOWED_RETURN_REASONS = [
    "Damaged product",
    "Melted chocolate",
    "Wrong product delivered",
    "Missing item",
    "Packaging issue",
    "Other issue",
]

SUPPORT_RETURN_STATUSES = [
    "Pending",
    "Under Review",
    "Approved",
    "Rejected",
    "Resolved",
]


class CreateReturnPayload(BaseModel):
    reason: str
    description: str = Field(..., min_length=5)
    photo_url: Optional[str] = None


class UpdateReturnStatusPayload(BaseModel):
    status: str
    admin_notes: Optional[str] = None


class ReturnRequestResponse(BaseModel):
    id: str
    order_id: str
    ticket_id: Optional[str] = None
    customer_id: str
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    order_amount: float
    payment_method: str
    delivery_address: Any
    delivered_at: datetime
    reason: str
    description: str
    photo_url: Optional[str] = None
    status: str
    admin_notes: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReturnPolicyResponse(BaseModel):
    return_requests_enabled: bool = True
    return_window_value: int = 30
    return_window_unit: str = "minutes"
    return_window_seconds: float = 1800.0
    return_photo_required: bool = False

    model_config = ConfigDict(from_attributes=True)

