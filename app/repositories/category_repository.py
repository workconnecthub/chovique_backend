from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.category import Category


class CategoryRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self) -> list[Category]:
        result = await self.db.execute(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order.asc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, category_id: str) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.id == category_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Category | None:
        result = await self.db.execute(
            select(Category).where(Category.slug == slug)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> Category:
        category = Category(**kwargs)
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)
        return category

    async def update(self, category_id: str, **kwargs) -> Category | None:
        await self.db.execute(
            update(Category)
            .where(Category.id == category_id)
            .values(**kwargs)
        )
        await self.db.commit()
        return await self.get_by_id(category_id)

    async def delete(self, category_id: str) -> bool:
        result = await self.db.execute(
            delete(Category).where(Category.id == category_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def get_category_product_summary(self, category_id: str) -> dict | None:
        category = await self.get_by_id(category_id)
        if not category:
            return None

        from app.models.product import Product
        result = await self.db.execute(
            select(Product).where(Product.category_id == category_id)
        )
        products = list(result.scalars().all())
        count = len(products)
        return {
            "category_id": category.id,
            "category_name": category.name,
            "product_count": count,
            "can_delete": count == 0,
            "products": [
                {
                    "id": p.id,
                    "name": p.name,
                    "price": p.price,
                    "stock": p.stock,
                    "image": p.image or (p.images[0] if p.images and len(p.images) > 0 else None),
                }
                for p in products
            ],
            "message": (
                f"If you want to delete this category, first you must remove or reassign the {count} product(s) which are existing based on this category."
                if count > 0
                else "Safe to delete: No products are currently assigned to this category."
            ),
        }

    async def count(self) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count()).select_from(Category))
        return result.scalar() or 0
