from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.wishlist import AddToWishlistPayload, SyncWishlistPayload, WishlistCountResponse, WishlistItemResponseSchema
from app.services.wishlist_service import WishlistService

router = APIRouter(prefix="/wishlist", tags=["Wishlist"])


@router.get("", response_model=list[WishlistItemResponseSchema], summary="Get user's wishlist")
async def get_wishlist(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WishlistService(db)
    return await service.get_wishlist(current_user.id)


@router.get("/count", response_model=WishlistCountResponse, summary="Get wishlist item count")
async def get_wishlist_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WishlistService(db)
    return await service.get_count(current_user.id)


@router.post("", response_model=WishlistItemResponseSchema, status_code=status.HTTP_201_CREATED, summary="Add item to wishlist")
async def add_to_wishlist(
    payload: AddToWishlistPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = WishlistService(db)
        return await service.add_to_wishlist(current_user.id, payload.product_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove item from wishlist")
async def remove_from_wishlist(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WishlistService(db)
    await service.remove_from_wishlist(current_user.id, product_id)


@router.get("/check/{product_id}", response_model=dict, summary="Check whether a product is wishlisted")
async def check_wishlist_status(
    product_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WishlistService(db)
    is_wishlisted = await service.is_product_wishlisted(current_user.id, product_id)
    return {"is_wishlisted": is_wishlisted}


@router.post("/sync", response_model=list[WishlistItemResponseSchema], summary="Sync guest wishlist items to user wishlist")
async def sync_wishlist(
    payload: SyncWishlistPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WishlistService(db)
    return await service.sync_wishlist(current_user.id, payload.product_ids)

