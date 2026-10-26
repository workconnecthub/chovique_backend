import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.models.order import Order
from app.models.user import User
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
class TestCancellationAndReturnPolicy:

    async def test_order_cancellation_within_24h(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order1 = Order(
                user_id=user_id,
                total=500.0,
                subtotal=500.0,
                status="Processing",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(hours=1),
            )
            session.add(order1)
            await session.commit()
            await session.refresh(order1)
            order_id = order1.id

        # GET /orders/{id}
        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["is_cancellable"] is True
        assert data["is_returnable"] is False

        # POST /orders/{id}/cancel
        res_cancel = await authenticated_client.post(f"/api/v1/orders/{order_id}/cancel")
        assert res_cancel.status_code == 200
        assert res_cancel.json()["status"] == "Cancelled"

    async def test_order_cancellation_at_23h59m(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order = Order(
                user_id=user_id,
                total=600.0,
                subtotal=600.0,
                status="Confirmed",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(hours=23, minutes=59),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["is_cancellable"] is True

    async def test_order_cancellation_exceeded_24h(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order = Order(
                user_id=user_id,
                total=700.0,
                subtotal=700.0,
                status="Processing",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(hours=25),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["is_cancellable"] is False

        # Attempt cancellation via API
        res_cancel = await authenticated_client.post(f"/api/v1/orders/{order_id}/cancel")
        assert res_cancel.status_code == 400
        assert "24 hours" in res_cancel.json()["detail"]

    async def test_shipped_order_cancellation_rejected(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order = Order(
                user_id=user_id,
                total=800.0,
                subtotal=800.0,
                status="Shipped",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(hours=5),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["is_cancellable"] is False

        res_cancel = await authenticated_client.post(f"/api/v1/orders/{order_id}/cancel")
        assert res_cancel.status_code == 400

    async def test_return_policy_within_30_minutes(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order = Order(
                user_id=user_id,
                total=900.0,
                subtotal=900.0,
                status="Delivered",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(days=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["is_cancellable"] is False
        assert data["is_returnable"] is True

        # Request return via API
        res_ret = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Melted chocolate", "description": "Chocolate arrived completely melted."}
        )
        assert res_ret.status_code == 200
        assert res_ret.json()["status"] == "Return Requested"

    async def test_return_policy_exceeded_30_minutes(self, authenticated_client: AsyncClient):
        async with TestSessionLocal() as session:
            user_res = await session.execute(select(User).where(User.email == "test@example.com"))
            usr = user_res.scalar_one_or_none()
            user_id = usr.id if usr else "customer1"

            now = datetime.now(timezone.utc)
            order = Order(
                user_id=user_id,
                total=1000.0,
                subtotal=1000.0,
                status="Delivered",
                payment_status="PAID",
                shipping_address={"name": "Test", "street": "123", "city": "City", "state": "State", "zip": "12345", "phone": "9999999999"},
                created_at=now - timedelta(days=2),
                delivered_at=now - timedelta(minutes=45),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        res = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res.status_code == 200
        assert res.json()["is_returnable"] is False

        res_ret = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Damaged product", "description": "Product packaging was damaged."}
        )
        assert res_ret.status_code == 400
        assert "30 minutes" in res_ret.json()["detail"].lower() or "expired" in res_ret.json()["detail"].lower()

