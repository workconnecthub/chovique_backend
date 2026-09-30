from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ==========================================================
# Nutrition Info
# ==========================================================

class NutritionInfo(BaseModel):
    servingSize: str = ""
    calories: str = ""
    totalFat: str = ""
    saturatedFat: str = ""
    transFat: str = ""
    cholesterol: str = ""
    sodium: str = ""
    totalCarb: str = ""
    dietaryFiber: str = ""
    totalSugars: str = ""
    addedSugars: str = ""
    protein: str = ""


# ==========================================================
# Review Response
# ==========================================================

class ReviewResponse(BaseModel):
    id: str
    author: str
    rating: float
    text: str
    date: str
    avatar: Optional[str] = None
    title: Optional[str] = None
    images: list[str] = []
    videos: list[str] = []
    is_verified_purchase: bool = False
    status: str = "approved"


# ==========================================================
# Product Response
# ==========================================================

class ProductResponse(BaseModel):
    id: str
    sku: Optional[str] = None
    name: str
    slug: str
    category_id: Optional[str] = None
    category: str
    price: float
    originalPrice: Optional[float] = None
    weight: Optional[str] = None
    stock: int = 0
    description: Optional[str] = None
    ingredients: Optional[str] = None
    badge: Optional[str] = None
    image: Optional[str] = None
    hoverImage: Optional[str] = None
    rating: float = 0.0
    ratingsCount: int = 0
    isAvailable: bool = True
    isFeatured: bool = False
    isBestseller: bool = False
    isNewArrival: bool = False
    images: list[str] = []
    reviews: list[ReviewResponse] = []

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_orm_model(cls, product) -> "ProductResponse":
        """Convert an ORM Product to a frontend-compatible response."""
        reviews = []
        if "reviews_list" in product.__dict__ and product.__dict__["reviews_list"]:
            reviews = [
                ReviewResponse(
                    id=r.id,
                    author=r.author,
                    rating=r.rating,
                    text=r.text,
                    date=r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
                    avatar=r.avatar,
                    title=getattr(r, "title", None),
                    images=getattr(r, "images", []) or [],
                    videos=getattr(r, "videos", []) or [],
                    is_verified_purchase=getattr(r, "is_verified_purchase", False),
                    status=getattr(r, "status", "approved"),
                )
                for r in product.__dict__["reviews_list"]
                if getattr(r, "status", "approved") == "approved"
            ]

        raw_stock = getattr(product, "stock", 0)
        stock_val = raw_stock if raw_stock is not None else 0

        raw_rating = getattr(product, "rating", 0.0)
        rating_val = float(raw_rating) if (raw_rating is not None and float(raw_rating) > 0) else 4.8

        cat_id = getattr(product, "category_id", None)
        cat_name = getattr(product, "category", "") or ""

        return cls(
            id=product.id,
            sku=getattr(product, "sku", None),
            name=product.name,
            slug=product.slug,
            category_id=cat_id,
            category=cat_name,
            price=product.price,
            originalPrice=product.original_price,
            weight=product.weight,
            stock=stock_val,
            description=product.description,
            ingredients=product.ingredients,
            badge=product.badge,
            image=product.image,
            hoverImage=product.hover_image,
            rating=rating_val,
            ratingsCount=product.ratings_count,
            isAvailable=getattr(product, "is_available", True),
            isFeatured=getattr(product, "is_featured", False),
            isBestseller=getattr(product, "is_bestseller", False),
            isNewArrival=getattr(product, "is_new_arrival", False),
            images=getattr(product, "images", []) or [],
            reviews=reviews,
        )


# ==========================================================
# Product Create
# ==========================================================

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    sku: Optional[str] = None
    category_id: Optional[str] = None
    category: Optional[str] = None
    price: float = Field(..., gt=0)
    original_price: Optional[float] = None
    weight: Optional[str] = None
    stock: int = 100
    description: Optional[str] = None
    ingredients: Optional[str] = None
    badge: Optional[str] = None
    image: Optional[str] = None
    hover_image: Optional[str] = None
    rating: float = 0.0
    ratings_count: int = 0
    sort_order: int = 0
    is_available: bool = True
    is_featured: bool = False
    is_bestseller: bool = False
    is_new_arrival: bool = False
    images: list[str] = []



# ==========================================================
# Product Update
# ==========================================================

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category_id: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    weight: Optional[str] = None
    stock: Optional[int] = None
    description: Optional[str] = None
    ingredients: Optional[str] = None
    badge: Optional[str] = None
    image: Optional[str] = None
    hover_image: Optional[str] = None
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    is_available: Optional[bool] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    is_featured: Optional[bool] = None
    is_bestseller: Optional[bool] = None
    is_new_arrival: Optional[bool] = None
    images: Optional[list[str]] = None



# ==========================================================
# Paginated Product Response
# ==========================================================

class PaginatedProductResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    per_page: int
    total_pages: int
