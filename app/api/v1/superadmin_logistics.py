from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.repositories.store_location_repository import StoreLocationRepository
from app.repositories.delivery_service_area_repository import DeliveryServiceAreaRepository
from app.schemas.shipping import (
    StoreLocationCreate,
    StoreLocationUpdate,
    StoreLocationResponse,
    DeliveryServiceAreaCreate,
    DeliveryServiceAreaUpdate,
    DeliveryServiceAreaResponse,
)

router = APIRouter(prefix="/superadmin/logistics", tags=["Superadmin Logistics"])


# =======================================================================
# Store Locations Management
# =======================================================================

@router.get(
    "/store-locations",
    response_model=List[StoreLocationResponse],
    summary="List all store locations (Superadmin only)",
)
@router.get(
    "/stores",
    response_model=List[StoreLocationResponse],
    summary="List all store locations (Superadmin only, alias)",
    include_in_schema=False,
)
async def list_store_locations(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = StoreLocationRepository(db)
    return await repo.get_all(active_only=active_only)


@router.post(
    "/store-locations",
    response_model=StoreLocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new store/warehouse location (Superadmin only)",
)
@router.post(
    "/stores",
    response_model=StoreLocationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new store/warehouse location (Superadmin only, alias)",
    include_in_schema=False,
)
async def create_store_location(
    payload: StoreLocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = StoreLocationRepository(db)
    return await repo.create(**payload.model_dump())


@router.put(
    "/store-locations/{store_id}",
    response_model=StoreLocationResponse,
    summary="Update store/warehouse location (Superadmin only)",
)
async def update_store_location(
    store_id: str,
    payload: StoreLocationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = StoreLocationRepository(db)
    updated = await repo.update(store_id, **payload.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store location not found.")
    return updated


@router.patch(
    "/store-locations/{store_id}/set-primary",
    response_model=StoreLocationResponse,
    summary="Set store as primary origin (Superadmin only)",
)
async def set_primary_store(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = StoreLocationRepository(db)
    updated = await repo.set_primary(store_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store location not found.")
    return updated


@router.delete(
    "/store-locations/{store_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate store location (Superadmin only)",
)
async def delete_store_location(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = StoreLocationRepository(db)
    success = await repo.delete(store_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store location not found.")


# =======================================================================
# Delivery Service Areas Management
# =======================================================================

@router.get(
    "/service-areas",
    response_model=List[DeliveryServiceAreaResponse],
    summary="List all delivery service areas (Superadmin only)",
)
async def list_service_areas(
    active_only: bool = False,
    mode: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = DeliveryServiceAreaRepository(db)
    return await repo.get_all(active_only=active_only, mode=mode)


@router.post(
    "/service-areas",
    response_model=DeliveryServiceAreaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or add a delivery service area (Superadmin only)",
)
async def create_service_area(
    payload: DeliveryServiceAreaCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = DeliveryServiceAreaRepository(db)
    existing = await repo.get_by_pincode(payload.pincode)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Service area rule for PIN code {payload.pincode} already exists.",
        )
    return await repo.create(**payload.model_dump())


@router.put(
    "/service-areas/{area_id}",
    response_model=DeliveryServiceAreaResponse,
    summary="Update delivery service area (Superadmin only)",
)
async def update_service_area(
    area_id: str,
    payload: DeliveryServiceAreaUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = DeliveryServiceAreaRepository(db)
    updated = await repo.update(area_id, **payload.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service area not found.")
    return updated


@router.delete(
    "/service-areas/{area_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete delivery service area (Superadmin only)",
)
async def delete_service_area(
    area_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    repo = DeliveryServiceAreaRepository(db)
    success = await repo.delete(area_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service area not found.")
