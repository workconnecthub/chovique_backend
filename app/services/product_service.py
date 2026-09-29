import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.product_repository import ProductRepository
from app.schemas.product import (
    PaginatedProductResponse,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
)

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Generate a URL-friendly slug from text."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text


class ProductService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.product_repo = ProductRepository(db)

    # ==========================================================
    # List Products (Paginated + Filtered)
    # ==========================================================

    async def list_products(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        availability: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        min_rating: float | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 12,
    ) -> PaginatedProductResponse:

        result = await self.product_repo.get_all(
            search=search,
            category=category,
            availability=availability,
            price_min=price_min,
            price_max=price_max,
            min_rating=min_rating,
            sort=sort,
            page=page,
            per_page=per_page,
        )

        return PaginatedProductResponse(
            items=[
                ProductResponse.from_orm_model(p)
                for p in result["items"]
            ],
            total=result["total"],
            page=result["page"],
            per_page=result["per_page"],
            total_pages=result["total_pages"],
        )

    # ==========================================================
    # Get Single Product
    # ==========================================================

    async def get_product(self, product_id: str) -> ProductResponse | None:

        product = await self.product_repo.get_by_id(product_id)

        if not product:
            return None

        return ProductResponse.from_orm_model(product)

    # ==========================================================
    # Create Product
    # ==========================================================

    async def create_product(
        self,
        data: ProductCreate,
    ) -> ProductResponse:

        slug = _slugify(data.name)

        # Check for duplicate slug
        existing = await self.product_repo.get_by_slug(slug)
        if existing:
            # Append a counter
            import uuid
            slug = f"{slug}-{str(uuid.uuid4())[:8]}"

        sku = data.sku
        if not sku:
            count = await self.product_repo.count()
            sku = f"CHO{count + 1:03d}"

        product = await self.product_repo.create(
            name=data.name,
            sku=sku,
            slug=slug,
            category_id=data.category_id,
            category=data.category,
            price=data.price,
            original_price=data.original_price,
            weight=data.weight,
            stock=data.stock,
            description=data.description,
            ingredients=data.ingredients,
            badge=data.badge,
            image=data.image,
            hover_image=data.hover_image,
            images=data.images,
            rating=data.rating,
            ratings_count=data.ratings_count,
            sort_order=data.sort_order,
            is_featured=data.is_featured,
            is_bestseller=data.is_bestseller,
            is_new_arrival=data.is_new_arrival,
        )

        logger.info("Product created: id=%s name=%s", product.id, product.name)

        return ProductResponse.from_orm_model(product)

    # ==========================================================
    # Update Product
    # ==========================================================

    async def update_product(
        self,
        product_id: str,
        data: ProductUpdate,
    ) -> ProductResponse | None:

        existing = await self.product_repo.get_by_id(product_id)

        if not existing:
            return None

        update_data = data.model_dump(exclude_unset=True)

        if not update_data:
            return ProductResponse.from_orm_model(existing)

        product = await self.product_repo.update(
            product_id,
            **update_data,
        )

        if product and product.stock is not None:
            try:
                from app.services.notification_service import NotificationService
                notif_svc = NotificationService(self.db)
                if product.stock == 0:
                    await notif_svc.notify_out_of_stock(product.id, product.name)
                elif product.stock <= 10:
                    await notif_svc.notify_low_stock(product.id, product.name, product.stock)
            except Exception as exc:
                logger.error("Failed to trigger stock notification on update: %s", exc)

        logger.info("Product updated: id=%s", product_id)

        return ProductResponse.from_orm_model(product)

    # ==========================================================
    # Delete Product
    # ==========================================================

    async def delete_product(self, product_id: str) -> bool:

        existing = await self.product_repo.get_by_id(product_id)

        if not existing:
            return False

        # Delete all associated S3 images before removing from DB
        from app.services.storage_service import storage_service

        images_to_delete: list[str] = []

        if existing.image:
            images_to_delete.append(existing.image)
        if existing.hover_image and existing.hover_image not in images_to_delete:
            images_to_delete.append(existing.hover_image)
        if existing.images:
            for img_url in existing.images:
                if img_url and img_url not in images_to_delete:
                    images_to_delete.append(img_url)

        for url in images_to_delete:
            public_id = storage_service.extract_public_id(url)
            if public_id:
                try:
                    storage_service.delete_media(public_id)
                except Exception as e:
                    logger.warning("Failed to delete S3 image '%s' for product %s: %s", public_id, product_id, e)

        await self.product_repo.delete(product_id)

        logger.info("Product deleted: id=%s (S3 images cleaned up: %d)", product_id, len(images_to_delete))

        return True

    # ==========================================================
    # Related Products & Recommendations
    # ==========================================================

    async def get_related_products(self, product_id: str, limit: int = 4) -> list[ProductResponse]:
        product = await self.product_repo.get_by_id(product_id)
        if not product:
            return []

        # Find products in same category, excluding the current one
        result = await self.product_repo.get_all(category=product.category, per_page=limit + 1)
        related = [p for p in result["items"] if str(p.id) != str(product_id)]

        # Fallback: if not enough category matches, fill up with other active products
        if len(related) < limit:
            all_result = await self.product_repo.get_all(per_page=limit + 5)
            existing_ids = {str(p.id) for p in related}
            existing_ids.add(str(product_id))
            for p in all_result["items"]:
                if str(p.id) not in existing_ids:
                    related.append(p)
                    existing_ids.add(str(p.id))
                    if len(related) >= limit:
                        break

        related = related[:limit]
        return [ProductResponse.from_orm_model(p) for p in related]

    async def get_recommendations(self, user_id: str | None = None, limit: int = 4) -> list[ProductResponse]:
        # For authenticated users, we could fetch their order history and recommend based on it.
        # But for simplicity, we'll just return bestsellers for everyone.
        # This can be expanded later.
        
        # A simple recommendation: return highly rated or bestsellers
        from sqlalchemy import select
        from app.models.product import Product
        
        stmt = select(Product).filter(Product.is_active == True).order_by(Product.rating.desc()).limit(limit)
        result = await self.db.execute(stmt)
        products = result.scalars().all()
        
        return [ProductResponse.from_orm_model(p) for p in products]

    async def get_products_bulk(self, product_ids: list[str]) -> list[ProductResponse]:
        if not product_ids:
            return []
            
        from sqlalchemy import select
        from app.models.product import Product
        
        stmt = select(Product).filter(Product.id.in_(product_ids), Product.is_active == True)
        result = await self.db.execute(stmt)
        products = result.scalars().all()
        
        # Keep original order based on product_ids array if possible
        products_dict = {str(p.id): p for p in products}
        ordered_products = [products_dict[pid] for pid in product_ids if pid in products_dict]
        
        return [ProductResponse.from_orm_model(p) for p in ordered_products]
