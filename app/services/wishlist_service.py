from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.product_repository import ProductRepository
from app.repositories.wishlist_repository import WishlistRepository
from app.schemas.product import ProductResponse
from app.schemas.wishlist import WishlistCountResponse, WishlistItemResponseSchema


class WishlistService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wishlist_repo = WishlistRepository(db)
        self.product_repo = ProductRepository(db)

    async def get_wishlist(self, user_id: str) -> list[WishlistItemResponseSchema]:
        items = await self.wishlist_repo.get_user_wishlist(user_id)
        return [
            WishlistItemResponseSchema(
                id=item.id,
                product=ProductResponse.from_orm_model(item.product),
            )
            for item in items
            if item.product and item.product.is_active
        ]

    async def add_to_wishlist(self, user_id: str, product_id: str) -> WishlistItemResponseSchema:
        product = await self.product_repo.get_by_id(product_id)
        if not product or not product.is_active:
            raise ValueError("Product not available.")

        item = await self.wishlist_repo.add_item(user_id, product_id)
        if not item:
            # Already in wishlist — return current item
            items = await self.wishlist_repo.get_user_wishlist(user_id)
            found = next((i for i in items if i.product_id == product_id), None)
            return WishlistItemResponseSchema(
                id=found.id if found else "existing",
                product=ProductResponse.from_orm_model(product),
            )

        return WishlistItemResponseSchema(
            id=item.id,
            product=ProductResponse.from_orm_model(product),
        )

    async def remove_from_wishlist(self, user_id: str, product_id: str) -> bool:
        return await self.wishlist_repo.remove_item(user_id, product_id)

    async def get_count(self, user_id: str) -> WishlistCountResponse:
        count = await self.wishlist_repo.get_count(user_id)
        return WishlistCountResponse(count=count)

    async def is_product_wishlisted(self, user_id: str, product_id: str) -> bool:
        items = await self.wishlist_repo.get_user_wishlist(user_id)
        return any(i.product_id == product_id for i in items)

    async def sync_wishlist(self, user_id: str, product_ids: list[str]) -> list[WishlistItemResponseSchema]:
        """
        Synchronize guest wishlist items into customer account.
        Validates that products exist and are active.
        Deduplicates items and is idempotent across multiple retries.
        """
        for prod_id in product_ids:
            product = await self.product_repo.get_by_id(prod_id)
            if product and product.is_active:
                await self.wishlist_repo.add_item(user_id, prod_id)

        return await self.get_wishlist(user_id)

