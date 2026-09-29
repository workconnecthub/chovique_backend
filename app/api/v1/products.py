import logging
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models.user import User
from app.schemas.product import (
    NutritionInfo,
    PaginatedProductResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ReviewResponse,
)
from app.services.storage_service import storage_service
from app.services.customer_service import CustomerService
from app.services.product_service import ProductService
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/products", tags=["Products"])


# ======================================================
# LIST PRODUCTS (Public)
# ======================================================

@router.get(
    "",
    response_model=PaginatedProductResponse,
    summary="List products with pagination, filtering, and sorting",
)
async def list_products(
    search: Optional[str] = Query(default=None, description="Search by name or description"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    availability: Optional[str] = Query(default=None, description="Filter by availability: in_stock, out_of_stock, all"),
    price_min: Optional[float] = Query(default=None, ge=0, description="Minimum price"),
    price_max: Optional[float] = Query(default=None, ge=0, description="Maximum price"),
    min_rating: Optional[float] = Query(default=None, ge=0, le=5, description="Minimum rating"),
    sort: Optional[str] = Query(default=None, description="Sort: price_asc, price_desc, rating, newest, name_asc, name_desc"),
    page: int = Query(default=1, ge=1, description="Page number"),
    per_page: int = Query(default=12, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)

    clean_cat = None
    if category and category.lower().strip() != "all":
        clean_cat = category.strip()

    return await service.list_products(
        search=search,
        category=clean_cat,
        availability=availability,
        price_min=price_min,
        price_max=price_max,
        min_rating=min_rating,
        sort=sort,
        page=page,
        per_page=per_page,
    )


# ======================================================
# GET SINGLE PRODUCT (Public)
# ======================================================

@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Get a single product by ID",
)
async def get_product(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    product = await service.get_product(product_id)

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return product


# ======================================================
# BULK & RECOMMENDATIONS (Public)
# ======================================================

@router.get(
    "/bulk",
    response_model=list[ProductResponse],
    summary="Get multiple products by IDs (useful for recently viewed)",
)
async def get_products_bulk(
    ids: str = Query(..., description="Comma-separated product IDs"),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    product_ids = [id.strip() for id in ids.split(",") if id.strip()]
    return await service.get_products_bulk(product_ids)

@router.get(
    "/recommendations",
    response_model=list[ProductResponse],
    summary="Get product recommendations",
)
async def get_recommendations(
    limit: int = Query(default=4, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
    # Optional auth to personalize later
):
    service = ProductService(db)
    return await service.get_recommendations(user_id=None, limit=limit)

@router.get(
    "/{product_id}/related",
    response_model=list[ProductResponse],
    summary="Get related products",
)
async def get_related_products(
    product_id: str,
    limit: int = Query(default=4, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    return await service.get_related_products(product_id, limit)


# ======================================================
# CREATE PRODUCT (Admin only)
# Accepts multipart/form-data matching frontend FormData
# ======================================================

@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new product (admin only)",
)
async def create_product(
    name: str = Form(...),
    category_id: Optional[str] = Form(default=None),
    category: Optional[str] = Form(default=None),
    price: float = Form(...),
    description: Optional[str] = Form(default=None),
    is_featured: Optional[bool] = Form(default=False),
    is_bestseller: Optional[bool] = Form(default=False),
    is_new_arrival: Optional[bool] = Form(default=False),
    original_price: Optional[float] = Form(default=None),
    weight: Optional[str] = Form(default=None),
    stock: Optional[int] = Form(default=10),
    ingredients: Optional[str] = Form(default=None),
    badge: Optional[str] = Form(default=None),
    rating: Optional[float] = Form(default=None),
    sort_order: int = Form(default=0),
    # Nutrition fields
    nutrition_serving_size: Optional[str] = Form(default=None),
    nutrition_calories: Optional[str] = Form(default=None),
    nutrition_total_fat: Optional[str] = Form(default=None),
    nutrition_saturated_fat: Optional[str] = Form(default=None),
    nutrition_trans_fat: Optional[str] = Form(default=None),
    nutrition_cholesterol: Optional[str] = Form(default=None),
    nutrition_sodium: Optional[str] = Form(default=None),
    nutrition_total_carb: Optional[str] = Form(default=None),
    nutrition_dietary_fiber: Optional[str] = Form(default=None),
    nutrition_total_sugars: Optional[str] = Form(default=None),
    nutrition_added_sugars: Optional[str] = Form(default=None),
    nutrition_protein: Optional[str] = Form(default=None),
    # Upload files
    image: Optional[UploadFile] = File(default=None),
    gallery_images: List[UploadFile] = File(default=[]),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    selected_category = category_id or category

    # Set badge if flags provided, and sync boolean flags with badge
    clean_badge = badge
    if is_bestseller:
        clean_badge = "Bestseller"
    elif is_new_arrival:
        clean_badge = "New"

    valid_badges = ["Bestseller", "New", "Premium", "Limited", "Gift Hamper", "Gift Hampers", "Signature"]
    if clean_badge and clean_badge not in valid_badges:
        clean_badge = None

    if clean_badge == "Bestseller":
        is_bestseller = True
    elif clean_badge == "New":
        is_new_arrival = True
    elif clean_badge in ("Premium", "Signature", "Gift Hamper", "Gift Hampers"):
        is_featured = True

    # Upload gallery images if provided first
    hover_image_url: Optional[str] = None
    gallery_urls: List[str] = []
    if gallery_images:
        g_files = gallery_images if isinstance(gallery_images, list) else [gallery_images]
        for g_file in g_files:
            if g_file and hasattr(g_file, "filename") and g_file.filename:
                g_url = await storage_service.upload_image(
                    file=g_file,
                    folder="chocolate-world/products",
                )
                gallery_urls.append(g_url)

    # Upload main image to S3 storage folder "chocolate-world/products"
    image_url: Optional[str] = None
    if image and hasattr(image, "filename") and image.filename:
        image_url = await storage_service.upload_image(
            file=image,
            folder="chocolate-world/products",
        )
    elif gallery_urls:
        image_url = gallery_urls[0]

    # Fallback placeholder image if none provided
    if not image_url:
        image_url = "https://images.unsplash.com/photo-1548907040-4d42b52115ca?auto=format&fit=crop&w=600&q=80"

    if gallery_urls:
        hover_image_url = gallery_urls[0]
    else:
        hover_image_url = image_url

    nutrition = None
    if any([
        nutrition_serving_size, nutrition_calories, nutrition_total_fat,
        nutrition_saturated_fat, nutrition_trans_fat, nutrition_cholesterol,
        nutrition_sodium, nutrition_total_carb, nutrition_dietary_fiber,
        nutrition_total_sugars, nutrition_added_sugars, nutrition_protein
    ]):
        nutrition = NutritionInfo(
            servingSize=nutrition_serving_size or "",
            calories=nutrition_calories or "",
            totalFat=nutrition_total_fat or "",
            saturatedFat=nutrition_saturated_fat or "",
            transFat=nutrition_trans_fat or "",
            cholesterol=nutrition_cholesterol or "",
            sodium=nutrition_sodium or "",
            totalCarb=nutrition_total_carb or "",
            dietaryFiber=nutrition_dietary_fiber or "",
            totalSugars=nutrition_total_sugars or "",
            addedSugars=nutrition_added_sugars or "",
            protein=nutrition_protein or "",
        )

    data = ProductCreate(
        name=name,
        category_id=selected_category,
        category=selected_category,
        price=price,
        original_price=original_price,
        weight=weight,
        stock=stock if stock is not None else 10,
        description=description,
        ingredients=ingredients,
        nutrition=nutrition,
        badge=clean_badge,
        rating=rating if (rating is not None and rating > 0) else 4.8,
        image=image_url,
        hover_image=hover_image_url,
        sort_order=sort_order,
        is_featured=is_featured or False,
        is_bestseller=is_bestseller or False,
        is_new_arrival=is_new_arrival or False,
    )

    service = ProductService(db)
    return await service.create_product(data)


# ======================================================
# UPDATE PRODUCT (Admin only)
# ======================================================

@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    summary="Update a product (admin only)",
)
async def update_product(
    product_id: str,
    data: ProductUpdate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    product = await service.update_product(product_id, data)

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return product


@router.post(
    "/{product_id}/image",
    response_model=ProductResponse,
    summary="Update a product's image (admin only)",
)
async def update_product_image(
    product_id: str,
    images: List[UploadFile] = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    product = await service.get_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    # Upload all new images
    image_urls = []
    for img in images:
        if img and hasattr(img, "filename") and img.filename:
            url = await storage_service.upload_image(
                file=img,
                folder="chocolate-world/products",
            )
            image_urls.append(url)

    if not image_urls:
        raise HTTPException(status_code=400, detail="No valid images provided")

    # Delete old main image if exists
    if product.image:
        public_id = storage_service.extract_public_id(product.image)
        if public_id:
            storage_service.delete_media(public_id)

    # Also delete old gallery images
    if product.images:
        for old_img in product.images:
            if old_img and old_img != product.image:
                public_id = storage_service.extract_public_id(old_img)
                if public_id:
                    storage_service.delete_media(public_id)

    updated_product = await service.update_product(
        product_id, 
        ProductUpdate(
            image=image_urls[0],
            hover_image=image_urls[0] if len(image_urls) == 1 else image_urls[1],
            images=image_urls
        )
    )
    return updated_product

# ======================================================
# DELETE PRODUCT (Admin only)
# ======================================================

@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product (admin only)",
)
async def delete_product(
    product_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = ProductService(db)
    deleted = await service.delete_product(product_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )


# ======================================================
# PRODUCT REVIEWS (Public / Customer)
# ======================================================
# REVIEWS & RATINGS
# ======================================================

class CreateReviewRequest(BaseModel):
    author: str
    rating: float = Field(..., ge=1, le=5)
    text: str

@router.get(
    "/{product_id}/reviews",
    summary="Get reviews and rating summary for a product",
)
async def get_product_reviews(
    product_id: str,
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    return await service.get_product_reviews_with_summary(product_id)

@router.post(
    "/{product_id}/reviews",
    status_code=status.HTTP_201_CREATED,
    summary="Post a review for a product (purchased customers only)",
)
async def create_product_review(
    product_id: str,
    payload: CreateReviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    return await service.create_product_review(
        product_id=product_id,
        author=payload.author or current_user.full_name,
        rating=payload.rating,
        text=payload.text,
        user_id=current_user.id,
        bypass_purchase_check=False,
    )

