import logging
import re
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.category_repository import CategoryRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.category import CategoryCreate, CategoryResponse, CategoryUpdate
from app.schemas.product import PaginatedProductResponse, ProductResponse

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text


class CategoryService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.category_repo = CategoryRepository(db)
        self.product_repo = ProductRepository(db)

    async def get_categories(self) -> list[CategoryResponse]:
        from sqlalchemy import select, func
        from app.models.product import Product

        categories = await self.category_repo.get_all()
        res = []
        for c in categories:
            count_res = await self.db.execute(
                select(func.count(Product.id)).where(Product.category_id == c.id)
            )
            p_count = int(count_res.scalar() or 0)
            data = CategoryResponse.model_validate(c)
            data.product_count = p_count
            res.append(data)
        return res

    async def get_category(self, category_id: str) -> CategoryResponse | None:
        category = await self.category_repo.get_by_id(category_id)
        if not category:
            return None
        return CategoryResponse.model_validate(category)

    async def get_category_by_slug(self, slug: str) -> CategoryResponse | None:
        category = await self.category_repo.get_by_slug(slug)
        if not category:
            return None
        return CategoryResponse.model_validate(category)

    async def get_category_products(
        self,
        slug: str,
        page: int = 1,
        per_page: int = 12,
    ) -> PaginatedProductResponse:

        category = await self.category_repo.get_by_slug(slug)
        category_filter = category.id if category else slug

        result = await self.product_repo.get_all(
            category=category_filter,
            page=page,
            per_page=per_page,
        )

        return PaginatedProductResponse(
            items=[ProductResponse.from_orm_model(p) for p in result["items"]],
            total=result["total"],
            page=result["page"],
            per_page=result["per_page"],
            total_pages=result["total_pages"],
        )

    async def create_category(self, data: CategoryCreate) -> CategoryResponse:
        slug = data.slug or _slugify(data.name)

        category = await self.category_repo.create(
            name=data.name,
            slug=slug,
            description=data.description,
            image_url=data.image_url,
            parent_id=data.parent_id,
            sort_order=data.sort_order,
        )
        return CategoryResponse.model_validate(category)

    async def update_category(self, category_id: str, data: CategoryUpdate) -> CategoryResponse | None:
        update_dict = data.model_dump(exclude_unset=True)
        category = await self.category_repo.update(category_id, **update_dict)
        if not category:
            return None
        return CategoryResponse.model_validate(category)

    async def delete_category(self, category_id: str) -> bool:
        summary = await self.category_repo.get_category_product_summary(category_id)
        if not summary:
            return False

        if summary["product_count"] > 0:
            prod_names = ", ".join([p["name"] for p in summary["products"][:3]])
            if summary["product_count"] > 3:
                prod_names += f" and {summary['product_count'] - 3} more"
            raise ValueError(
                f"Cannot delete category '{summary['category_name']}'. "
                f"There are {summary['product_count']} product(s) currently assigned to this category ({prod_names}). "
                f"If you want to delete this category, first you must remove or reassign the products which are existing based on this category."
            )

        return await self.category_repo.delete(category_id)

    async def get_category_product_summary(self, category_id: str) -> dict | None:
        return await self.category_repo.get_category_product_summary(category_id)
