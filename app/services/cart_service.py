import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart import CartItem
from app.repositories.cart_repository import CartRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.cart import CartItemResponseSchema, CartResponseSchema
from app.schemas.product import ProductResponse

logger = logging.getLogger(__name__)


class CartService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cart_repo = CartRepository(db)
        self.product_repo = ProductRepository(db)

    async def get_cart(self, user_id: str) -> CartResponseSchema:
        """
        Fetch cart and recalculate subtotal and item count on EVERY request.
        Validates product availability and latest price.
        """
        cart = await self.cart_repo.get_or_create_user_cart(user_id)

        items_response = []
        subtotal = 0.0
        item_count = 0

        for item in cart.items:
            product = item.product
            # Validate product is active
            if product and product.is_active and getattr(product, "is_available", True) is not False:
                prod_res = ProductResponse.from_orm_model(product)
                subtotal += product.price * item.quantity
                item_count += item.quantity
                items_response.append(
                    CartItemResponseSchema(
                        id=item.id,
                        product=prod_res,
                        quantity=item.quantity,
                    )
                )

        return CartResponseSchema(
            id=cart.id,
            items=items_response,
            subtotal=round(subtotal, 2),
            item_count=item_count,
        )

    async def add_to_cart(self, user_id: str, product_id: str, quantity: int = 1) -> CartResponseSchema:
        product = await self.product_repo.get_by_id(product_id)
        if not product or not product.is_active or getattr(product, "is_available", True) is False or product.stock <= 0:
            raise ValueError("Product is out of stock.")

        if product.stock < quantity:
            raise ValueError(f"Insufficient stock available. Only {product.stock} items left.")

        cart = await self.cart_repo.get_or_create_user_cart(user_id)
        await self.cart_repo.add_or_update_item(cart.id, product_id, quantity)

        return await self.get_cart(user_id)

    async def update_quantity(self, user_id: str, product_id: str, quantity: int) -> CartResponseSchema:
        if quantity > 0:
            product = await self.product_repo.get_by_id(product_id)
            if not product or not product.is_active:
                raise ValueError("Product is not available.")
            if product.stock < quantity:
                raise ValueError(f"Insufficient stock available. Only {product.stock} items left.")

        cart = await self.cart_repo.get_or_create_user_cart(user_id)
        await self.cart_repo.update_item_quantity(cart.id, product_id, quantity)

        return await self.get_cart(user_id)

    async def remove_item(self, user_id: str, product_id: str) -> CartResponseSchema:
        cart = await self.cart_repo.get_or_create_user_cart(user_id)
        await self.cart_repo.remove_item(cart.id, product_id)
        return await self.get_cart(user_id)

    async def clear_cart(self, user_id: str) -> CartResponseSchema:
        cart = await self.cart_repo.get_or_create_user_cart(user_id)
        await self.cart_repo.clear_cart(cart.id)
        return await self.get_cart(user_id)

    async def sync_cart(self, user_id: str, items: list) -> CartResponseSchema:
        """
        Synchronize guest cart items with authenticated customer cart.
        Quantity policy:
          - If product already in authenticated cart: min(max(existing_qty, guest_qty), product.stock)
          - If product not in authenticated cart: min(guest_qty, product.stock)
        Ensures idempotency (retries do not duplicate quantities) and enforces stock availability.
        Existing authenticated items not in guest cart are preserved.
        """
        cart = await self.cart_repo.get_or_create_user_cart(user_id)
        existing_items = {item.product_id: item for item in (cart.items or [])}

        for item in items:
            product = await self.product_repo.get_by_id(item.product_id)
            if (
                not product
                or not product.is_active
                or getattr(product, "is_available", True) is False
                or product.stock <= 0
            ):
                continue

            if item.product_id in existing_items:
                existing_item = existing_items[item.product_id]
                new_qty = min(max(existing_item.quantity, item.quantity), product.stock)
                if new_qty > 0 and new_qty != existing_item.quantity:
                    await self.cart_repo.update_item_quantity(cart.id, item.product_id, new_qty)
                    existing_item.quantity = new_qty
            else:
                new_qty = min(item.quantity, product.stock)
                if new_qty > 0:
                    new_item = CartItem(cart_id=cart.id, product_id=item.product_id, quantity=new_qty)
                    self.db.add(new_item)
                    await self.db.commit()
                    await self.db.refresh(new_item)
                    existing_items[item.product_id] = new_item

        return await self.get_cart(user_id)

