import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.delivery_service_area_repository import DeliveryServiceAreaRepository
from app.repositories.platform_settings_repository import PlatformSettingsRepository
from app.repositories.store_location_repository import StoreLocationRepository
from app.schemas.shipping import ShippingCalculateResponse
from app.services.shipping.local_provider import LocalDeliveryProvider
from app.services.shipping.ithink_logistics_provider import IThinkLogisticsProvider

logger = logging.getLogger(__name__)


class FulfillmentRoutingService:
    """
    Central authoritative service for fulfillment routing decisions.
    Determines whether a destination is LOCAL delivery or THIRD-PARTY COURIER.
    Uses configurable database service areas rather than hardcoded string logic.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.store_repo = StoreLocationRepository(db)
        self.service_area_repo = DeliveryServiceAreaRepository(db)
        self.ps_repo = PlatformSettingsRepository(db)
        self.local_provider = LocalDeliveryProvider()
        self.courier_provider = IThinkLogisticsProvider()

    async def calculate_shipping(
        self,
        pincode: str,
        cart_total: float = 0.0,
        city: Optional[str] = None,
        state: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
    ) -> ShippingCalculateResponse:
        clean_pin = str(pincode or "").strip()
        subtotal_dec = Decimal(str(max(0.0, float(cart_total or 0.0))))

        # 1. Fetch primary origin store
        primary_store = await self.store_repo.get_primary_store()
        origin_pin = primary_store.pincode if primary_store else "530017"
        origin_name = primary_store.name if primary_store else "Chovique Flagship Store"
        origin_id = primary_store.id if primary_store else None

        # 2. Fetch platform global settings (for fallback free shipping threshold)
        ps = await self.ps_repo.get()
        platform_free_threshold = (
            Decimal(str(ps.free_shipping_min_order))
            if getattr(ps, "free_shipping_min_order", 0) > 0
            else None
        )

        # 3. Check explicit service area rule
        area = await self.service_area_repo.get_active_by_pincode(clean_pin)

        # Case A: Explicit LOCAL service area
        if area and area.delivery_mode == "LOCAL":
            configured_charge = Decimal(str(area.delivery_charge))
            free_threshold = (
                Decimal(str(area.free_delivery_threshold))
                if area.free_delivery_threshold is not None and area.free_delivery_threshold > 0
                else platform_free_threshold
            )

            rate = await self.local_provider.calculate_rate(
                origin_pincode=origin_pin,
                destination_pincode=clean_pin,
                subtotal=subtotal_dec,
                configured_charge=configured_charge,
                free_threshold=free_threshold,
            )
            final_rate = float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            is_free = (final_rate == 0.0 and configured_charge > 0)

            return ShippingCalculateResponse(
                serviceable=True,
                fulfillment_type="LOCAL",
                shipping_provider="INTERNAL",
                delivery_charge=final_rate,
                free_delivery_applied=is_free,
                service_area=f"{area.city} ({clean_pin})",
                estimated_delivery=area.estimated_delivery or "Within 3-5 hours (Same Day)",
                message="Local fast delivery available to your address",
                origin_store=origin_name,
                origin_store_id=origin_id,
            )

        # Case B: Explicit UNAVAILABLE service area
        if area and area.delivery_mode == "UNAVAILABLE":
            return ShippingCalculateResponse(
                serviceable=False,
                fulfillment_type="LOCAL",
                shipping_provider="INTERNAL",
                delivery_charge=0.0,
                free_delivery_applied=False,
                service_area=None,
                estimated_delivery="N/A",
                message="Sorry, delivery is currently unavailable for this location.",
                origin_store=origin_name,
                origin_store_id=origin_id,
            )

        # Case C: Explicit COURIER service area OR fallback to general courier if valid Indian pincode
        if area and area.delivery_mode == "COURIER":
            configured_charge = Decimal(str(area.delivery_charge))
            free_threshold = (
                Decimal(str(area.free_delivery_threshold))
                if area.free_delivery_threshold is not None and area.free_delivery_threshold > 0
                else platform_free_threshold
            )
            rate = await self.courier_provider.calculate_rate(
                origin_pincode=origin_pin,
                destination_pincode=clean_pin,
                subtotal=subtotal_dec,
                configured_charge=configured_charge,
                free_threshold=free_threshold,
            )
            final_rate = float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            is_free = (final_rate == 0.0 and configured_charge > 0)

            return ShippingCalculateResponse(
                serviceable=True,
                fulfillment_type="COURIER",
                shipping_provider=self.courier_provider.provider_name(),
                delivery_charge=final_rate,
                free_delivery_applied=is_free,
                service_area=f"{area.city} ({clean_pin})",
                estimated_delivery=area.estimated_delivery or "2-4 Business Days",
                message="Courier delivery available to your address",
                origin_store=origin_name,
                origin_store_id=origin_id,
            )

        # Case D: Not in local service area -> Automatic Courier routing if valid Indian 6-digit postal code
        if len(clean_pin) == 6 and clean_pin.isdigit() and clean_pin[0] != "0":
            # Standard courier charge (e.g. standard_shipping_charge from platform settings, or base rate ₹80)
            default_courier_charge = (
                Decimal(str(ps.standard_shipping_charge))
                if getattr(ps, "standard_shipping_charge", 0) > 0
                else Decimal("80.00")
            )
            rate = await self.courier_provider.calculate_rate(
                origin_pincode=origin_pin,
                destination_pincode=clean_pin,
                subtotal=subtotal_dec,
                configured_charge=default_courier_charge,
                free_threshold=platform_free_threshold,
            )
            final_rate = float(rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            is_free = (final_rate == 0.0 and default_courier_charge > 0)

            return ShippingCalculateResponse(
                serviceable=True,
                fulfillment_type="COURIER",
                shipping_provider=self.courier_provider.provider_name(),
                delivery_charge=final_rate,
                free_delivery_applied=is_free,
                service_area=city or "Standard Courier Zone",
                estimated_delivery="2-4 Business Days",
                message="Courier delivery available to your destination",
                origin_store=origin_name,
                origin_store_id=origin_id,
            )

        # Case E: Invalid or unsupported destination
        return ShippingCalculateResponse(
            serviceable=False,
            fulfillment_type="COURIER",
            shipping_provider="INTERNAL",
            delivery_charge=0.0,
            free_delivery_applied=False,
            service_area=None,
            estimated_delivery="N/A",
            message="Sorry, delivery is currently unavailable for this location.",
            origin_store=origin_name,
            origin_store_id=origin_id,
        )
