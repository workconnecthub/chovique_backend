from decimal import Decimal
from typing import Optional, Dict, Any
from app.services.shipping.base import BaseShippingProvider


class LocalDeliveryProvider(BaseShippingProvider):
    """
    Internal Chovique fleet delivery provider.
    Calculates rate based on local service-area configuration and handles
    fleet delivery assignment eligibility.
    """

    def __init__(self, default_charge: Decimal = Decimal("40.00")):
        self.default_charge = default_charge

    async def check_serviceability(
        self,
        origin_pincode: str,
        destination_pincode: str,
        **kwargs,
    ) -> Dict[str, Any]:
        return {
            "serviceable": True,
            "fulfillment_type": "LOCAL",
            "shipping_provider": "INTERNAL",
            "estimated_delivery": "Within 3-5 hours (Same Day)",
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

        charge = configured_charge if configured_charge is not None else self.default_charge
        return charge
