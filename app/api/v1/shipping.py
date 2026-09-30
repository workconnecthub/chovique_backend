import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.shipping import ShippingCalculateRequest, ShippingCalculateResponse
from app.services.fulfillment_routing_service import FulfillmentRoutingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shipping", tags=["Shipping & Logistics"])


@router.post(
    "/calculate",
    response_model=ShippingCalculateResponse,
    summary="Calculate authoritative shipping fee and determine fulfillment mode (LOCAL vs COURIER)",
)
async def calculate_shipping(
    payload: ShippingCalculateRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        routing_service = FulfillmentRoutingService(db)
        return await routing_service.calculate_shipping(
            pincode=payload.pincode,
            cart_total=payload.get_subtotal(),
            city=payload.city,
            state=payload.state,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Shipping calculation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to calculate shipping at this time.",
        )
