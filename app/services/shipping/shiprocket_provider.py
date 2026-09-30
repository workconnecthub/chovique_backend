from decimal import Decimal
from typing import Optional, Dict, Any
from app.services.shipping.courier_provider import CourierProvider


class ShiprocketProvider(CourierProvider):
    """
    Shiprocket adapter placeholder and rate estimation provider.
    Decoupled from order core: ready to connect to Shiprocket REST API in the future courier phase.
    """

    def __init__(self, base_rate: Decimal = Decimal("85.00")):
        self.base_rate = base_rate

    def provider_name(self) -> str:
        return "SHIPROCKET"

    async def check_serviceability(
        self,
        origin_pincode: str,
        destination_pincode: str,
        **kwargs,
    ) -> Dict[str, Any]:
        # Basic validation for valid Indian 6-digit postal code
        pin = str(destination_pincode or "").strip()
        if len(pin) == 6 and pin.isdigit():
            return {
                "serviceable": True,
                "fulfillment_type": "COURIER",
                "shipping_provider": "SHIPROCKET",
                "estimated_delivery": "2-4 Business Days",
            }
        return {
            "serviceable": False,
            "fulfillment_type": "COURIER",
            "shipping_provider": "SHIPROCKET",
            "message": "Courier delivery unavailable for this postal code",
        }

    async def calculate_rate(
        self,
        origin_pincode: str,
        destination_pincode: str,
        subtotal: Decimal,
        configured_charge: Optional[Decimal] = None,
        free_threshold: Optional[Decimal] = None,
        **kwargs,
    ) -> Decimal:
        if free_threshold is not None and subtotal >= free_threshold:
            return Decimal("0.00")

        if configured_charge is not None:
            return configured_charge

        return self.base_rate
