"""
Customer API tests.

Covers: profile update, avatar upload, address book, coupon validation,
order placement & list, support tickets, notifications, contact form, product reviews.
"""

import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient

from app.services.superadmin_service import ensure_superadmin_exists
from app.models.coupon import Coupon
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


from sqlalchemy import select
from app.models.coupon import Coupon
from app.models.product import Product
from app.models.ticket import SupportTicket

async def _seed():
    async with TestSessionLocal() as session:
        await ensure_superadmin_exists(session)
        res = await session.execute(select(Coupon).where(Coupon.code == "CHOVIQUE10"))
        if not res.scalar_one_or_none():
            coupon = Coupon(
                code="CHOVIQUE10",
                name="Chovique 10",
                description="10% off for test",
                coupon_type="CUSTOMER",
                discount_type="PERCENTAGE",
                discount_percent=10.0,
                discount_amount=0.0,
                is_active=True,
            )
            session.add(coupon)
        
        prod_res = await session.execute(select(Product).where(Product.id == "p1"))
        if not prod_res.scalar_one_or_none():
            product = Product(
                id="p1",
                name="Dark Truffle",
                slug="dark-truffle",
                description="Rich dark chocolate truffle",
                price=849.0,
                stock=100,
                is_active=True,
                is_featured=True,
            )
            session.add(product)
        await session.commit()


# ==========================================================
# Profile & Address Tests
# ==========================================================

class TestCustomerProfileAndAddress:

    async def test_update_profile(self, authenticated_client: AsyncClient):
        response = await authenticated_client.patch(
            "/api/v1/users/me",
            json={
                "phone": "+91 99999 88888",
                "gender": "male",
                "address_city": "Mumbai",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["profile"]["phone"] == "9999988888"
        assert data["profile"]["gender"] == "male"
        assert data["profile"]["address"]["city"] == "Mumbai"

    async def test_add_and_list_address(self, authenticated_client: AsyncClient):
        # Add address
        res = await authenticated_client.post(
            "/api/v1/users/me/addresses",
            json={
                "title": "Home",
                "name": "Test User",
                "street": "123 Chocolate Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
                "phone": "+91 98765 43210",
                "isDefault": True,
            },
        )
        assert res.status_code == 201
        addr = res.json()
        assert addr["title"] == "Home"
        assert addr["isDefault"] is True

        # Get list
        res_list = await authenticated_client.get("/api/v1/users/me/addresses")
        assert res_list.status_code == 200
        addresses = res_list.json()
        assert len(addresses) == 1
        assert addresses[0]["id"] == addr["id"]

    async def test_set_default_and_delete_address(self, authenticated_client: AsyncClient):
        # Create address 1
        res1 = await authenticated_client.post(
            "/api/v1/users/me/addresses",
            json={
                "title": "Home",
                "name": "Test User",
                "street": "123 Street",
                "city": "Mumbai",
                "state": "MH",
                "zip": "400001",
                "phone": "9876543210",
                "isDefault": True,
            },
        )
        addr1_id = res1.json()["id"]

        # Create address 2
        res2 = await authenticated_client.post(
            "/api/v1/users/me/addresses",
            json={
                "title": "Office",
                "name": "Test User",
                "street": "456 Office Rd",
                "city": "Mumbai",
                "state": "MH",
                "zip": "400002",
                "phone": "9876543210",
                "isDefault": False,
            },
        )
        addr2_id = res2.json()["id"]

        # Set address 2 as default
        def_res = await authenticated_client.patch(
            f"/api/v1/users/me/addresses/{addr2_id}/default"
        )
        assert def_res.status_code == 200
        assert def_res.json()["isDefault"] is True

        # Delete address 1
        del_res = await authenticated_client.delete(
            f"/api/v1/users/me/addresses/{addr1_id}"
        )
        assert del_res.status_code == 204


# ==========================================================
# Coupon Tests
# ==========================================================

class TestCoupons:

    async def test_validate_coupon_success(self, client: AsyncClient):
        await _seed()
        res = await client.post(
            "/api/v1/coupons/validate",
            json={"code": "CHOVIQUE10"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is True
        assert data["discount_percent"] == 10.0

    async def test_validate_coupon_invalid(self, client: AsyncClient):
        await _seed()
        res = await client.post(
            "/api/v1/coupons/validate",
            json={"code": "INVALIDCODE"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False

    async def test_validate_expired_coupon(self, client: AsyncClient):
        """An expired coupon must be rejected by /coupons/validate."""
        async with TestSessionLocal() as session:
            expired_coupon = Coupon(
                code="EXPIRED10",
                description="Expired test coupon",
                discount_percent=10.0,
                discount_amount=0.0,
                is_active=True,
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
            session.add(expired_coupon)
            await session.commit()

        res = await client.post(
            "/api/v1/coupons/validate",
            json={"code": "EXPIRED10"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False
        assert data["message"] == "Invalid or expired promo code."

    async def test_validate_inactive_coupon(self, client: AsyncClient):
        """An is_active=False coupon must be rejected by /coupons/validate."""
        async with TestSessionLocal() as session:
            inactive_coupon = Coupon(
                code="INACTIVE10",
                description="Inactive test coupon",
                discount_percent=10.0,
                discount_amount=0.0,
                is_active=False,
                expires_at=None,
            )
            session.add(inactive_coupon)
            await session.commit()

        res = await client.post(
            "/api/v1/coupons/validate",
            json={"code": "INACTIVE10"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["valid"] is False
        assert data["message"] == "Invalid or expired promo code."

    async def test_user_coupons_list(self, authenticated_client: AsyncClient):
        await _seed()
        res = await authenticated_client.get("/api/v1/users/me/coupons")
        assert res.status_code == 200
        coupons = res.json()
        assert len(coupons) > 0
        for c in coupons:
            assert "code" in c
            assert "status" in c
            if c.get("expires_at"):
                assert c.get("expiryDate") is not None
                assert c.get("expiry_date") is not None

    async def test_used_coupon_excluded_from_available_and_retained_in_history(
        self, authenticated_client: AsyncClient
    ):
        """
        When a customer uses a coupon in an order:
        1. /coupons/available must NOT include the used coupon.
        2. /users/me/coupons must still include the coupon, marked as 'Used'.
        3. /coupons/validate must reject the coupon for that user.
        4. Subsequent order placement with that coupon must fail.
        """
        await _seed()

        # Before order: coupon is available in both endpoints
        avail_res = await authenticated_client.get("/api/v1/coupons/available")
        assert avail_res.status_code == 200
        avail_codes = [c["code"] for c in avail_res.json()]
        assert "CHOVIQUE10" in avail_codes

        history_res = await authenticated_client.get("/api/v1/users/me/coupons")
        assert history_res.status_code == 200
        chovique_coupon = next((c for c in history_res.json() if c["code"] == "CHOVIQUE10"), None)
        assert chovique_coupon is not None
        assert chovique_coupon["status"] == "Available"

        # Place order using CHOVIQUE10
        order_payload = {
            "items": [{"product_id": "p1", "quantity": 1}],
            "shipping_address": {
                "name": "Jane Doe",
                "phone": "+919876543210",
                "street": "123 Chocolate Lane",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
            },
            "delivery_option": "STANDARD",
            "payment_method": "COD",
            "coupon_code": "CHOVIQUE10",
        }
        order_res = await authenticated_client.post("/api/v1/orders", json=order_payload)
        assert order_res.status_code == 201

        # After order:
        # 1. /coupons/available must NOT include CHOVIQUE10
        avail_res2 = await authenticated_client.get("/api/v1/coupons/available")
        assert avail_res2.status_code == 200
        avail_codes2 = [c["code"] for c in avail_res2.json()]
        assert "CHOVIQUE10" not in avail_codes2

        # 2. /users/me/coupons must still include CHOVIQUE10, with status 'Used'
        history_res2 = await authenticated_client.get("/api/v1/users/me/coupons")
        assert history_res2.status_code == 200
        chovique_coupon2 = next((c for c in history_res2.json() if c["code"] == "CHOVIQUE10"), None)
        assert chovique_coupon2 is not None
        assert chovique_coupon2["status"] == "Used"

        # 3. /coupons/validate must reject the coupon for this customer
        val_res = await authenticated_client.post(
            "/api/v1/coupons/validate",
            json={"code": "CHOVIQUE10"},
        )
        assert val_res.status_code == 200
        val_data = val_res.json()
        assert val_data["valid"] is False
        assert "already used" in val_data["message"].lower()

        # 4. Attempting to place another order with CHOVIQUE10 must fail
        dup_order_res = await authenticated_client.post("/api/v1/orders", json=order_payload)
        assert dup_order_res.status_code == 400



# ==========================================================
# Orders Tests
# ==========================================================

class TestOrders:

    async def test_place_and_get_order(self, authenticated_client: AsyncClient):
        await _seed()

        order_payload = {
            "items": [{"product_id": "p1", "quantity": 2}],
            "shipping_address": {
                "name": "Test User",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
                "phone": "+91 98765 43210",
            },
            "delivery_option": "Express Delivery",
            "payment_method": "UPI",
            "coupon_code": "CHOVIQUE10",
        }

        res = await authenticated_client.post("/api/v1/orders", json=order_payload)
        assert res.status_code == 201, f"POST /api/v1/orders failed: {res.text}"
        order = res.json()
        assert order["id"].startswith("ORD-")
        assert len(order["items"]) == 1
        assert order["subtotal"] == 1698.0
        assert order["discount"] == 169.8
        assert order["status"] == "Processing"

        # Fetch user orders
        orders_res = await authenticated_client.get("/api/v1/orders")
        assert orders_res.status_code == 200
        orders = orders_res.json()
        assert len(orders) == 1
        assert orders[0]["id"] == order["id"]

        # Fetch single order
        single_res = await authenticated_client.get(f"/api/v1/orders/{order['id']}")
        assert single_res.status_code == 200
        assert single_res.json()["id"] == order["id"]

    async def test_place_order_with_unselected_coins(self, authenticated_client: AsyncClient):
        """When Use Available Coins is unselected (coins_to_use=0), order is placed normally with 0 coin discount."""
        await _seed()
        payload = {
            "items": [{"product_id": "p1", "quantity": 1}],
            "shipping_address": {
                "name": "Coins Test User",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
                "phone": "9876543210",
            },
            "delivery_option": "Standard Delivery",
            "payment_method": "UPI",
            "coins_to_use": 0,
        }
        res = await authenticated_client.post("/api/v1/orders", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["coins_used"] == 0
        assert data["coin_discount"] == 0.0

    async def test_place_order_insufficient_coins_validation(self, authenticated_client: AsyncClient):
        """When requested coins exceed wallet balance, the request is rejected with 400."""
        await _seed()
        payload = {
            "items": [{"product_id": "p1", "quantity": 1}],
            "shipping_address": {
                "name": "Coins Test User",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
                "phone": "9876543210",
            },
            "delivery_option": "Standard Delivery",
            "payment_method": "UPI",
            "coins_to_use": 999999,
        }
        res = await authenticated_client.post("/api/v1/orders", json=payload)
        assert res.status_code == 400
        assert "Insufficient coin balance" in res.json().get("detail", "")

    async def test_order_placement_atomicity_on_failure(self, authenticated_client: AsyncClient):
        """When order placement fails due to invalid stock, the transaction is rolled back and no order is created in DB."""
        await _seed()
        
        # Get count of orders before attempt
        initial_orders_res = await authenticated_client.get("/api/v1/orders")
        initial_count = len(initial_orders_res.json())

        payload = {
            "items": [{"product_id": "p1", "quantity": 99999}],  # Out of stock quantity
            "shipping_address": {
                "name": "Stock Test User",
                "street": "123 Main St",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
                "phone": "9876543210",
            },
            "delivery_option": "Standard Delivery",
            "payment_method": "UPI",
            "coupon_code": "CHOVIQUE10",
        }
        res = await authenticated_client.post("/api/v1/orders", json=payload)
        assert res.status_code == 400

        # Check that no new order was created in DB
        after_orders_res = await authenticated_client.get("/api/v1/orders")
        assert len(after_orders_res.json()) == initial_count


# ==========================================================
# Support Tickets & Notifications Tests
# ==========================================================

class TestSupportAndNotifications:

    async def test_create_and_feedback_ticket(self, authenticated_client: AsyncClient):
        res = await authenticated_client.post(
            "/api/v1/support/tickets",
            json={
                "category": "Chocolate melted",
                "description": "My chocolate melted during delivery.",
            },
        )
        assert res.status_code == 201
        ticket = res.json()
        assert ticket["id"].startswith("TKT-")
        assert ticket["category"] == "Chocolate melted"
        assert ticket["status"] == "Pending"

        # List tickets
        list_res = await authenticated_client.get("/api/v1/support/tickets")
        assert list_res.status_code == 200
        assert len(list_res.json()) == 1

        # Resolve ticket first so feedback can be submitted
        async with TestSessionLocal() as session:
            t_obj = await session.get(SupportTicket, ticket["id"])
            if t_obj:
                t_obj.status = "Resolved"
                await session.commit()

        # Submit feedback
        fb_res = await authenticated_client.post(
            f"/api/v1/support/tickets/{ticket['id']}/feedback",
            json={"feedback": "Resolved"},
        )
        assert fb_res.status_code == 200
        assert fb_res.json()["customerResolutionFeedback"] == "Resolved"

    async def test_notifications(self, authenticated_client: AsyncClient):
        # Create ticket triggers a notification
        ticket_res = await authenticated_client.post(
            "/api/v1/support/tickets",
            json={
                "category": "Other",
                "description": "General question.",
            },
        )
        assert ticket_res.status_code == 201

        # Check unread count
        count_res = await authenticated_client.get("/api/v1/users/me/notifications/unread-count")
        assert count_res.status_code == 200
        assert count_res.json()["unread_count"] >= 1

        # Get notification list
        res = await authenticated_client.get("/api/v1/users/me/notifications")
        assert res.status_code == 200
        notifs = res.json()
        assert len(notifs) >= 1
        notif = next((n for n in notifs if n.get("type") == "support"), notifs[0])
        assert notif["type"] == "support"
        assert notif["is_read"] is False
        assert notif["read"] is False
        notif_id = notif["id"]

        # Test unread query param filter
        unread_res = await authenticated_client.get("/api/v1/users/me/notifications?is_read=false")
        assert unread_res.status_code == 200
        assert len(unread_res.json()) >= 1
        for n in unread_res.json():
            assert n["is_read"] is False

        # Mark single read
        read_res = await authenticated_client.patch(
            f"/api/v1/users/me/notifications/{notif_id}/read"
        )
        assert read_res.status_code == 200
        assert read_res.json()["read"] is True
        assert read_res.json()["is_read"] is True

        # Test read-all
        read_all_res = await authenticated_client.post("/api/v1/users/me/notifications/read-all")
        assert read_all_res.status_code == 200
        assert "message" in read_all_res.json()

        # Unread count should now be 0
        count_after = await authenticated_client.get("/api/v1/users/me/notifications/unread-count")
        assert count_after.status_code == 200
        assert count_after.json()["unread_count"] == 0

        # Delete notification
        del_res = await authenticated_client.delete(
            f"/api/v1/users/me/notifications/{notif_id}"
        )
        assert del_res.status_code == 204


# ==========================================================
# Contact Form Tests
# ==========================================================

class TestContactForm:

    async def test_submit_contact(self, client: AsyncClient):
        res = await client.post(
            "/api/v1/contact",
            json={
                "name": "Jane Doe",
                "email": "jane@example.com",
                "phone": "+91 99999 00000",
                "subject": "Corporate Order Query",
                "message": "Interested in bulk hampers for festive season.",
            },
        )
        assert res.status_code == 201
        assert "Thanks" in res.json()["message"]


# ==========================================================
# Product Review Tests
# ==========================================================

class TestProductReviews:

    async def test_add_and_get_reviews(self, authenticated_client: AsyncClient):
        await _seed()

        # Add review
        res = await authenticated_client.post(
            "/api/v1/products/p1/reviews",
            json={
                "author": "Chef Ravi",
                "rating": 5.0,
                "text": "Best dark chocolate bar in the market!",
            },
        )
        assert res.status_code == 201
        rev = res.json()
        assert rev["author"] == "Chef Ravi"
        assert rev["rating"] == 5.0

        # Newly created reviews are pending admin moderation; approve for public retrieval test
        from app.models.review import ProductReview
        async with TestSessionLocal() as session:
            r_obj = await session.get(ProductReview, rev["id"])
            if r_obj:
                r_obj.status = "approved"
                await session.commit()

        # Get product reviews
        get_res = await authenticated_client.get("/api/v1/products/p1/reviews")
        assert get_res.status_code == 200
        data = get_res.json()
        reviews = data.get("reviews", data) if isinstance(data, dict) else data
        assert len(reviews) >= 1
        assert any(r.get("author") == "Chef Ravi" for r in reviews)


# ==========================================================
# 24-Hour Cancellation & 4-Day Return Policy Tests
# ==========================================================

from app.models.order import Order
from app.models.user import User

class TestCancellationAndReturnPolicy:

    async def test_order_cancellation_within_24h(self, authenticated_client: AsyncClient):
        await _seed()
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
        await _seed()
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
        await _seed()
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
        await _seed()
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
        await _seed()
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
            json={"reason": "Wrong product delivered", "description": "Wrong flavor received in box"}
        )
        assert res_ret.status_code == 200
        assert res_ret.json()["status"] == "Return Requested"

    async def test_return_policy_exceeded_30_minutes(self, authenticated_client: AsyncClient):
        await _seed()
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
            json={"reason": "Damaged product", "description": "Damaged box upon arrival"}
        )
        assert res_ret.status_code == 400
        assert "30 minutes" in res_ret.json()["detail"].lower() or "expired" in res_ret.json()["detail"].lower()
