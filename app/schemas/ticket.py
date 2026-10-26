from typing import Optional, Any
from pydantic import BaseModel, ConfigDict


class CreateTicketPayload(BaseModel):
    category: str
    description: str
    order_id: Optional[str] = None
    orderId: Optional[str] = None


class TicketFeedbackPayload(BaseModel):
    feedback: str  # 'Resolved' | 'Not Resolved'


class UpdateTicketStatusPayload(BaseModel):
    status: str
    admin_notes: Optional[str] = None


class SupportTicketResponse(BaseModel):
    id: str
    customerId: str
    customerName: str
    category: str
    description: str
    status: str
    orderId: Optional[str] = None
    order_id: Optional[str] = None
    adminNotes: Optional[str] = None
    customerResolutionFeedback: Optional[str] = None
    date: str
    notified: bool
    photo_url: Optional[str] = None
    photoUrl: Optional[str] = None
    return_request_id: Optional[str] = None
    returnRequestId: Optional[str] = None
    order_amount: Optional[float] = None
    orderAmount: Optional[float] = None
    payment_method: Optional[str] = None
    paymentMethod: Optional[str] = None
    delivery_address: Optional[Any] = None
    deliveryAddress: Optional[Any] = None
    delivered_at: Optional[str] = None
    deliveredAt: Optional[str] = None
    return_reason: Optional[str] = None
    returnReason: Optional[str] = None
    customer_email: Optional[str] = None
    customerEmail: Optional[str] = None
    customer_phone: Optional[str] = None
    customerPhone: Optional[str] = None
    currency: str = "₹"
    assigned_admin: Optional[str] = None
    assignedAdmin: Optional[str] = None
    created_at: Optional[str] = None
    createdAt: Optional[str] = None
    updated_at: Optional[str] = None
    updatedAt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
