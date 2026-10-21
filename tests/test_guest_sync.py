"""
Tests for guest cart and wishlist synchronization endpoints:
- POST /api/v1/cart/sync
- POST /api/v1/wishlist/sync

Verifies:
- Safe and idempotent merging of guest cart into customer account
- Protection against duplicate additions on network retries
- Stock clamping and filtering of invalid/inactive products
- Preservation of existing customer items
- Wishlist deduplication and active product filtering
- Authentication requirements (401 / 403 when unauthenticated)
"""

import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product

pytestmark = pytest.mark.asyncio


async def _create_test_product(
    db: AsyncSession,
    name: str = "Artisan Dark Chocolate",
    price: float = 12.99,
    stock: int = 10,
    is_active: bool = True,
    is_available: bool = True,
) -> Product:
    prod = Product(
        id=str(uuid.uuid4()),
        name=name,
        slug=f"test-{uuid.uuid4().hex[:8]}",
        price=price,
        stock=stock,
        is_active=is_active,
        is_available=is_available,
    )
    db.add(prod)
    await db.commit()
    await db.refresh(prod)
    return prod


class TestGuestCartSync:

    async def test_cart_sync_unauthenticated_fails(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/cart/sync",
            json={"items": [{"product_id": "prod-1", "quantity": 2}]},
        )
        assert response.status_code in (401, 403)

    async def test_cart_sync_empty_account(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
    ):
        prod = await _create_test_product(db_session, name="Truffle Box", stock=15)

        response = await authenticated_client.post(
            "/api/v1/cart/sync",
            json={"items": [{"product_id": prod.id, "quantity": 3}]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["product"]["id"] == prod.id
        assert data["items"][0]["quantity"] == 3

    async def test_cart_sync_idempotency_on_retry(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """Calling sync multiple times with the same payload must not duplicate quantities."""
        prod = await _create_test_product(db_session, name="Hazelnut Praline", stock=20)

        payload = {"items": [{"product_id": prod.id, "quantity": 2}]}

        # First sync
        res1 = await authenticated_client.post("/api/v1/cart/sync", json=payload)
        assert res1.status_code == 200
        assert res1.json()["items"][0]["quantity"] == 2

        # Second sync (simulating retry / multiple calls)
        res2 = await authenticated_client.post("/api/v1/cart/sync", json=payload)
        assert res2.status_code == 200
        # Quantity should still be 2, NOT 4!
        assert len(res2.json()["items"]) == 1
        assert res2.json()["items"][0]["quantity"] == 2

    async def test_cart_sync_preserves_existing_and_clamps_to_stock(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
    ):
        # Product 1: already in cart with qty 2, guest has qty 4, stock is 3 -> capped to 3
        prod1 = await _create_test_product(db_session, name="Limited Truffle", stock=3)
        # Product 2: already in cart with qty 1, not in guest cart -> preserved
        prod2 = await _create_test_product(db_session, name="Milk Bar", stock=50)

        # Pre-populate authenticated cart
        add_res1 = await authenticated_client.post(
            "/api/v1/cart",
            json={"product_id": prod1.id, "quantity": 2},
        )
        assert add_res1.status_code == 200
        add_res2 = await authenticated_client.post(
            "/api/v1/cart",
            json={"product_id": prod2.id, "quantity": 1},
        )
        assert add_res2.status_code == 200

        # Guest sync with prod1 qty 4
        sync_res = await authenticated_client.post(
            "/api/v1/cart/sync",
            json={"items": [{"product_id": prod1.id, "quantity": 4}]},
        )
        assert sync_res.status_code == 200
        items = {item["product"]["id"]: item["quantity"] for item in sync_res.json()["items"]}

        # Prod1 is capped to available stock (3)
        assert items[prod1.id] == 3
        # Prod2 is preserved with quantity 1
        assert items[prod2.id] == 1


class TestGuestWishlistSync:

    async def test_wishlist_sync_unauthenticated_fails(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/wishlist/sync",
            json={"product_ids": ["prod-1"]},
        )
        assert response.status_code in (401, 403)

    async def test_wishlist_sync_merges_and_deduplicates(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
    ):
        prod1 = await _create_test_product(db_session, name="Ruby Chocolate")
        prod2 = await _create_test_product(db_session, name="Gold Caramel")

        # Pre-add prod1 to authenticated wishlist
        add_res = await authenticated_client.post(
            "/api/v1/wishlist",
            json={"product_id": prod1.id},
        )
        assert add_res.status_code in (200, 201)

        # Sync guest wishlist containing prod1 (duplicate) and prod2 (new), with repeat
        sync_res = await authenticated_client.post(
            "/api/v1/wishlist/sync",
            json={"product_ids": [prod1.id, prod2.id, prod2.id]},
        )
        assert sync_res.status_code == 200
        items = sync_res.json()
        assert isinstance(items, list)
        wishlist_product_ids = [item["product"]["id"] for item in items]

        assert len(wishlist_product_ids) == 2
        assert prod1.id in wishlist_product_ids
        assert prod2.id in wishlist_product_ids

    async def test_wishlist_sync_filters_inactive_products(
        self,
        authenticated_client: AsyncClient,
        db_session: AsyncSession,
    ):
        active_prod = await _create_test_product(db_session, name="Active Bar", is_active=True)
        inactive_prod = await _create_test_product(db_session, name="Archived Bar", is_active=False)

        sync_res = await authenticated_client.post(
            "/api/v1/wishlist/sync",
            json={"product_ids": [active_prod.id, inactive_prod.id, "nonexistent-id"]},
        )
        assert sync_res.status_code == 200
        items = sync_res.json()
        assert isinstance(items, list)
        wishlist_product_ids = [item["product"]["id"] for item in items]

        assert wishlist_product_ids == [active_prod.id]
