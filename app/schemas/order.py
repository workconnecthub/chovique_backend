from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from app.schemas.product import ProductResponse


class ShippingAddressSchema(BaseModel):
    name: str
    street: str
    city: str
    state: str
    zip: str
    phone: str
    house_number: Optional[str] = None
    area: Optional[str] = None
    landmark: Optional[str] = None
    district: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    formatted_address: Optional[str] = None
    google_place_id: Optional[str] = None
    location_source: Optional[str] = "MANUAL"
    location_verified: Optional[bool] = False
    delivery_charge: Optional[float] = None
    delivery_type: Optional[str] = None


class OrderItemPayload(BaseModel):
    product_id: str
    quantity: int = 1


class OrderPayload(BaseModel):
    items: Optional[list[OrderItemPayload]] = []
    shipping_address: ShippingAddressSchema
    delivery_option: str = "Standard Delivery"
    payment_method: str = "UPI"
    coupon_code: Optional[str] = None
    coins_to_use: int = 0


class CartItemResponse(BaseModel):
    product: ProductResponse
    quantity: int


class OrderItemResponse(BaseModel):
    product: ProductResponse
    quantity: int
    price: float
    
    model_config = ConfigDict(from_attributes=True)


class OrderReturnPayload(BaseModel):
    reason: Optional[str] = None


class OrderResponse(BaseModel):
    id: str
    items: list[OrderItemResponse]
    total: float
    subtotal: float
    discount: float
    coupon_code: Optional[str] = None
    coupon_discount: float = 0.0
    coins_used: int = 0
    coin_discount: float = 0.0
    coins_earned: int = 0
    shipping: float
    tax: float = 0.0
    date: str
    status: str
    payment_status: str = "PENDING"
    shippingAddress: ShippingAddressSchema
    shipping_address: Optional[ShippingAddressSchema] = None
    deliveryOption: str
    paymentMethod: str
    fulfillment_type: Optional[str] = "LOCAL"
    shipping_provider: Optional[str] = "INTERNAL"
    fulfillment_status: Optional[str] = "UNASSIGNED"
    delivery_boy_id: Optional[str] = None
    delivery_boy_name: Optional[str] = None
    delivery_boy_phone: Optional[str] = None
    store_location_id: Optional[str] = None
    store_name: Optional[str] = None
    invoice_url: Optional[str] = None
    user_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    is_cancellable: bool = False
    is_returnable: bool = False
    created_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    customer_whatsapp_url: Optional[str] = None
    owner_whatsapp_url: Optional[str] = None

    # Delivery OTP workflow
    delivery_otp: Optional[str] = None
    delivery_otp_expires_at: Optional[datetime] = None
    delivery_accepted_at: Optional[datetime] = None
    delivery_rejected_at: Optional[datetime] = None
    delivery_rejection_reason: Optional[str] = None
    delivery_picked_at: Optional[datetime] = None

    # Shipping snapshot
    shipping_name: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_house_number: Optional[str] = None
    shipping_street: Optional[str] = None
    shipping_area: Optional[str] = None
    shipping_landmark: Optional[str] = None
    shipping_city: Optional[str] = None
    shipping_district: Optional[str] = None
    shipping_state: Optional[str] = None
    shipping_pincode: Optional[str] = None
    shipping_latitude: Optional[float] = None
    shipping_longitude: Optional[float] = None
    shipping_formatted_address: Optional[str] = None
    shipping_location_verified: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)

    def model_post_init(self, __context) -> None:
        if self.shipping_address is None and self.shippingAddress is not None:
            self.shipping_address = self.shippingAddress
        elif self.shippingAddress is None and self.shipping_address is not None:
            self.shippingAddress = self.shipping_address

