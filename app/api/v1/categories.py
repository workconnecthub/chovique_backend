from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.schemas.product import PaginatedProductResponse
from app.services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["Categories"])


@router.get("", response_model=list[CategoryResponse], summary="List all active categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    service = CategoryService(db)
    return await service.get_categories()


@router.get("/{id_or_slug}", response_model=CategoryResponse, summary="Get category by ID or Slug")
async def get_category(id_or_slug: str, db: AsyncSession = Depends(get_db)):
    service = CategoryService(db)
    category = await service.get_category(id_or_slug)
    if not category:
        category = await service.get_category_by_slug(id_or_slug)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return category


@router.get("/{slug}/products", response_model=PaginatedProductResponse, summary="Get products by category slug")
async def get_category_products(
    slug: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=12, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    service = CategoryService(db)
    return await service.get_category_products(slug=slug, page=page, per_page=per_page)


@router.post("", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, summary="Create category (admin only)")
async def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = CategoryService(db)
    return await service.create_category(payload)


@router.patch("/{category_id}", response_model=CategoryResponse, summary="Update category (admin only)")
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = CategoryService(db)
    category = await service.update_category(category_id, payload)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return category


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete category (admin only)")
async def delete_category(
    category_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = CategoryService(db)
    try:
        deleted = await service.delete_category(category_id)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/{category_id}/product-summary", summary="Get category product summary (admin only)")
async def get_category_product_summary(
    category_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = CategoryService(db)
    summary = await service.get_category_product_summary(category_id)
    if not summary:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return summary
