import re
from datetime import date, datetime
from typing import Optional, Generic, TypeVar, Union
from pydantic import BaseModel, field_validator, model_validator

from app.schemas.user import UserResponse
from app.schemas.order import OrderResponse
from app.schemas.ticket import SupportTicketResponse

T = TypeVar('T')

PHONE_REGEX = re.compile(r"^(\+91[\-\s]?)?[0]?[6-9]\d{9}$|^\+?[0-9\s\-()]{7,15}$")
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    total_pages: int


class MonthlyRevenue(BaseModel):
    month: str          # e.g. "Jan 2025"
    online_revenue: float
    offline_revenue: float
    total: float


class DailySalesPoint(BaseModel):
    name: str          # e.g. "05 Aug"
    sales: float
    orders_count: int = 0


class TopProduct(BaseModel):
    name: str
    units_sold: int
    stock: int
    revenue: float


class DashboardStatsFilterParams(BaseModel):
    preset: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode='after')
    def validate_date_range(self):
        if self.start_date and self.end_date:
            if self.start_date > self.end_date:
                raise ValueError("Start date cannot be after end date.")
        return self


class DashboardStatsResponse(BaseModel):
    # Basic counts
    total_sales: float
    total_orders: int
    total_customers: int
    total_products: int
    low_stock_products_count: int
    pending_tickets_count: int
    # Extended KPI metrics
    total_units_sold: int
    total_inventory_stock: int
    total_online_revenue: float
    total_offline_revenue: float
    admin_count: int
    reward_coins_issued: int = 0
    # Comparison percentage metrics
    revenue_change_percent: float = 12.5
    orders_change_percent: float = 8.2
    customers_change_percent: float = 6.7
    coins_change_percent: float = 13.3
    # Chart data
    monthly_revenue: list[MonthlyRevenue]
    daily_sales: list[DailySalesPoint] = []
    top_products: list[TopProduct]


class AuditLogEntry(BaseModel):
    id: str
    action: str
    user_name: Optional[str]
    user_email: Optional[str]
    resource: Optional[str]
    details: Optional[str]
    created_at: str  # ISO format string


class CustomerListItem(BaseModel):
    id: str
    name: str
    email: str
    phone: str = ""
    is_active: bool = True
    orders_count: int = 0
    total_spent: float = 0.0
    reward_coins: int = 0
    joined_date: str = ""
    created_at: str = ""
    avatar_url: Optional[str] = None
    avatar: Optional[str] = None


class CustomerSummaryStats(BaseModel):
    total_customers: int = 0
    active_accounts: int = 0
    total_orders_placed: int = 0
    lifetime_spend: float = 0.0


class CustomerListPaginatedResponse(BaseModel):
    items: list[CustomerListItem]
    total: int
    page: int
    limit: int
    total_pages: int
    summary: CustomerSummaryStats


class CustomerCoinsResponse(BaseModel):
    customer_id: str
    customer_name: str
    coin_balance: int
    rupee_value: float
    transactions: list[dict] = []


class CustomerDetailsResponse(BaseModel):
    user: UserResponse
    total_spent: float
    total_orders: int
    reward_coins: int = 0
    joined_date: str = ""
    recent_orders: list[OrderResponse]
    support_tickets: list[SupportTicketResponse]
    default_address: Optional[dict] = None
    addresses: list[dict] = []


class CustomerUpdatePayload(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_street: Optional[str] = None
    address_city: Optional[str] = None
    address_state: Optional[str] = None
    address_zip: Optional[str] = None
    is_active: Optional[bool] = True

    @field_validator("full_name", mode="before")
    @classmethod
    def validate_full_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("full_name cannot be empty or whitespace-only.")
        v_trimmed = str(v).strip()
        if len(v_trimmed) < 2:
            raise ValueError("full_name must be at least 2 characters long.")
        return v_trimmed

    @field_validator("email", mode="before")
    @classmethod
    def validate_and_normalize_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("email cannot be empty.")
        v_norm = str(v).strip().lower()
        if not EMAIL_REGEX.match(v_norm):
            raise ValueError("Please provide a valid email address.")
        return v_norm

    @field_validator("phone", mode="before")
    @classmethod
    def validate_and_normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            raise ValueError("phone cannot be empty.")
        v_trimmed = str(v).strip()
        if not PHONE_REGEX.match(v_trimmed):
            raise ValueError("Please provide a valid phone number (e.g. +91 9876543210 or 9876543210).")
        # Normalize by removing extra dashes/spaces
        cleaned = re.sub(r"[^\d+]", "", v_trimmed)
        return cleaned


class CreateCustomerRequest(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    password: Optional[str] = "Customer@123"
    gender: Optional[str] = None
    house_number: Optional[str] = None
    street: Optional[str] = None
    area: Optional[str] = None
    landmark: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    is_active: bool = True

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        v_clean = v.strip()
        if len(v_clean) < 2:
            raise ValueError("Full name must be at least 2 characters.")
        return v_clean

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v_clean = v.strip().lower()
        if not EMAIL_REGEX.match(v_clean):
            raise ValueError("Please provide a valid email address.")
        return v_clean

    @field_validator("phone", mode="before")
    @classmethod
    def validate_and_normalize_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not str(v).strip():
            return None
        v_trimmed = str(v).strip()
        if not PHONE_REGEX.match(v_trimmed):
            raise ValueError("Please provide a valid phone number (e.g. +91 9876543210 or 9876543210).")
        return re.sub(r"[^\d+]", "", v_trimmed)



class UpdateOrderStatusPayload(BaseModel):
    status: Optional[str] = None      # Order Status: Pending / Confirmed / Processing / Shipped / Out for Delivery / Delivered / Cancelled / Returned
    payment_status: Optional[str] = None  # Payment Status: Pending / Processing / Paid / Failed / Cancelled / Refund Pending / Refunded / Partially Refunded


class FulfillmentStatusPayload(BaseModel):
    """Payload for updating order fulfillment status only."""
    status: str
    notes: Optional[str] = None  # Optional admin note for audit log

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v_clean = v.strip()
        if v_clean == "Out_For_Delivery":
            v_clean = "Out for Delivery"
        valid = {
            "Pending",
            "Confirmed",
            "Processing",
            "Shipped",
            "Out for Delivery",
            "Delivered",
            "Cancelled",
            "Returned",
        }
        # Case-insensitive match to canonical title
        valid_map = {s.lower(): s for s in valid}
        if v_clean.lower() not in valid_map:
            raise ValueError(f"Invalid order status '{v}'. Must be one of: {', '.join(sorted(valid))}")
        return valid_map[v_clean.lower()]


class PaymentStatusPayload(BaseModel):
    """Payload for updating payment status."""
    payment_status: str
    is_cod_override: bool = False   # True = admin manually marking COD as paid
    notes: Optional[str] = None     # Optional admin note for audit log

    @field_validator("payment_status")
    @classmethod
    def validate_payment_status(cls, v: str) -> str:
        v_clean = v.strip()
        if v_clean.upper() == "REFUND_PENDING":
            v_clean = "Refund Pending"
        elif v_clean.upper() == "PARTIALLY_REFUNDED":
            v_clean = "Partially Refunded"
            
        valid = {
            "Pending",
            "Processing",
            "Paid",
            "Failed",
            "Cancelled",
            "Refund Pending",
            "Refunded",
            "Partially Refunded",
        }
        valid_map = {s.lower(): s for s in valid}
        if v_clean.lower() not in valid_map:
            raise ValueError(f"Invalid payment status '{v}'. Must be one of: {', '.join(sorted(valid))}")
        return valid_map[v_clean.lower()]


class OrderSummaryStats(BaseModel):
    """KPI snapshot included in the paginated orders list response."""
    total_orders: int
    processing: int = 0
    confirmed: int = 0
    shipped: int = 0
    out_for_delivery: int = 0
    delivered: int = 0
    cancelled: int = 0
    pending: int = 0
    returned: int = 0
    pending_payment: int = 0
    paid: int = 0
    failed_payment: int = 0
    refunded: int = 0
    refund_pending: int = 0
    partially_refunded: int = 0
    total_revenue: float = 0.0  # Sum of non-cancelled orders
    local_orders: int = 0
    courier_orders: int = 0
    unassigned_local: int = 0


class AdminOrderListResponse(BaseModel):
    """Paginated response for the admin order list endpoint."""
    items: list[OrderResponse]
    total: int
    page: int
    limit: int
    total_pages: int
    summary: OrderSummaryStats


# OfflineSale schemas

class OfflineSaleItemPayload(BaseModel):
    product_id: str
    quantity: int


class OfflineSalePayload(BaseModel):
    # Company Details
    company_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None

    # Transaction Details
    payment_method: str = "Cash"
    discount: float = 0.0
    tax: float = 0.0

    # Payment-Method-Specific Details
    payment_status: Optional[str] = "Paid"
    received_amount: Optional[float] = None
    receipt_number: Optional[str] = None
    card_type: Optional[str] = None
    card_last4: Optional[str] = None
    transaction_id: Optional[str] = None
    upi_id: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder: Optional[str] = None

    # Multi-product items
    items: Optional[list[OfflineSaleItemPayload]] = None

    # Legacy single-product fallback fields
    product_name: Optional[str] = None
    quantity: Optional[int] = 1
    total_price: Optional[float] = None


class OfflineSaleItemResponse(BaseModel):
    id: str
    product_id: Optional[str] = None
    product_name: str
    sku: Optional[str] = None
    unit_price: float
    quantity: int
    line_total: float


class OfflineSaleResponse(BaseModel):
    id: str
    receipt_id: str
    company_name: str
    contact_person: str
    phone: str
    email: Optional[str] = ""
    address: str
    payment_method: str
    subtotal: float
    discount: float
    tax: float
    total_amount: float
    status: str
    date: str
    created_at: str
    items: list[OfflineSaleItemResponse] = []

    # Payment-Method-Specific Response Details
    payment_status: Optional[str] = "Paid"
    received_amount: Optional[float] = None
    receipt_number: Optional[str] = None
    card_type: Optional[str] = None
    card_last4: Optional[str] = None
    transaction_id: Optional[str] = None
    upi_id: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder: Optional[str] = None

    # Backward compatibility fields for legacy frontend callers
    productName: str
    quantity: int
    totalPrice: float
    paymentMethod: str


# Ticket resolve payload

class ResolveTicketPayload(BaseModel):
    admin_notes: Optional[str] = None


# Banner image upload response

class BannerImageResponse(BaseModel):
    image_url: str


class ImportSalesResponse(BaseModel):
    imported: int
    skipped: int
    message: str


class CreateAdminRequest(BaseModel):
    full_name: str
    email: str
    password: str
    role: str = "admin"

    @field_validator("full_name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Full name is required.")
        return v.strip()

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v or "@" not in v:
            raise ValueError("Valid email address is required.")
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if not v or len(v) < 6:
            raise ValueError("Password must be at least 6 characters.")
        return v


class UpdateAdminPasswordPayload(BaseModel):
    password: str


class UpdateAdminRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None


# ======================================================
# CMS — Banners
# ======================================================

class CreateBannerRequest(BaseModel):
    title: str
    subtitle: str
    tag: str
    image: Optional[str] = None
    button_text: str
    link: str
    sort_order: int = 0
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def title_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Banner title is required.")
        return v.strip()

class UpdateBannerRequest(BaseModel):
    title: Optional[str] = None
    subtitle: Optional[str] = None
    tag: Optional[str] = None
    image: Optional[str] = None
    button_text: Optional[str] = None
    link: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


# ======================================================
# CMS — Testimonials
# ======================================================

class CreateTestimonialRequest(BaseModel):
    author: str
    title: Optional[str] = None
    text: str
    rating: float = 5.0
    initials: Optional[str] = None
    avatar_url: Optional[str] = None
    is_active: bool = True
    sort_order: int = 0


# ======================================================
# CMS — Instagram Reels
# ======================================================

class CreateReelRequest(BaseModel):
    video_url: Optional[str] = None
    instagram_url: Optional[str] = None
    account_name: Optional[str] = "@chovique_chocolatier"
    likes: Optional[str] = "0"
    comments: Optional[str] = "0"
    views: Optional[str] = "0 views"
    title: Optional[str] = "Instagram Reel"
    sort_order: int = 0
    is_active: bool = True


class ReelResponse(BaseModel):
    id: str
    videoUrl: Optional[str] = None
    instagramUrl: Optional[str] = None
    accountName: Optional[str] = "@chovique_chocolatier"
    likes: Optional[str] = "0"
    comments: Optional[str] = "0"
    views: Optional[str] = "0 views"
    title: Optional[str] = "Instagram Reel"


# ======================================================
# CMS — Site Config (Stats / Contact)
# ======================================================

class SetStatsRequest(BaseModel):
    happy_customers: int = 50000
    products_available: Optional[int] = 120
    orders_delivered: Optional[int] = 1500
    customer_rating_percent: Optional[int] = 98

    # Optional legacy fallback fields
    unique_flavors: Optional[int] = None
    countries_shipped: Optional[int] = None
    five_star_reviews_percent: Optional[int] = None


class SetContactRequest(BaseModel):
    email: Optional[str] = "support@chovique.com"
    phone: Optional[str] = "+91 83098 54870"
    whatsapp: Optional[str] = "+91 83098 54870"
    support_hours: Optional[str] = "Mon - Sat: 10:00 AM - 8:00 PM | Sunday: 11:00 AM - 6:00 PM"
    address: Optional[str] = "42, MG Road, Indiranagar, Bangalore, Karnataka 560038"
    instagram: Optional[str] = "https://instagram.com"
    facebook: Optional[str] = "https://facebook.com"
    twitter: Optional[str] = "https://x.com"