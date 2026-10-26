import pytest
import io
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy import select

from app.models.order import Order
from app.models.return_request import ReturnRequest
from app.models.ticket import SupportTicket
from app.models.user import User
from app.core.security import hash_password, create_access_token
from tests.conftest import TestSessionLocal


@pytest.mark.asyncio
class TestReturnRequestFeature:

    async def _setup_users(self):
        """Helper to create customer1, customer2, and admin users."""
        async with TestSessionLocal() as session:
            # Customer 1
            res1 = await session.execute(select(User).where(User.email == "test@example.com"))
            c1 = res1.scalar_one_or_none()
            if not c1:
                c1 = User(
                    email="test@example.com",
                    full_name="Customer One",
                    role="customer",
                    hashed_password=hash_password("Pass123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(c1)

            # Customer 2
            res2 = await session.execute(select(User).where(User.email == "other@example.com"))
            c2 = res2.scalar_one_or_none()
            if not c2:
                c2 = User(
                    email="other@example.com",
                    full_name="Customer Two",
                    role="customer",
                    hashed_password=hash_password("Pass123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(c2)

            # Admin
            res3 = await session.execute(select(User).where(User.email == "admin@chovique.com"))
            adm = res3.scalar_one_or_none()
            if not adm:
                adm = User(
                    email="admin@chovique.com",
                    full_name="Admin User",
                    role="admin",
                    hashed_password=hash_password("AdminPass123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(adm)

            await session.commit()
            await session.refresh(c1)
            await session.refresh(c2)
            await session.refresh(adm)
            return c1.id, c2.id, adm.id

    async def _get_admin_client(self, client: AsyncClient, admin_id: str):
        token = create_access_token(str(admin_id))
        client.cookies.set("access_token", token)
        client.headers["Authorization"] = f"Bearer {token}"
        return client


    # 1. Successful return request within 30 minutes (COD and Online payment)
    async def test_successful_return_request_within_30_minutes_cod(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=1450.0,
                subtotal=1450.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PENDING",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=2),
                delivered_at=now - timedelta(minutes=15),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Submit return request
        payload = {
            "reason": "Melted chocolate",
            "description": "Chocolate truffles were completely melted upon opening the package.",
        }
        res = await authenticated_client.post(f"/api/v1/orders/{order_id}/return", json=payload)
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "Return Requested"
        assert data["return_request"] is not None
        assert data["return_request"]["order_id"] == order_id
        assert data["return_request"]["reason"] == "Melted chocolate"
        assert data["return_request"]["status"] == "Pending"
        assert data["return_request"]["payment_method"] == "Cash on Delivery"
        assert data["return_request"]["order_amount"] == 1450.0

        # Verify ReturnRequest record & SupportTicket in DB
        async with TestSessionLocal() as session:
            ret_res = await session.execute(select(ReturnRequest).where(ReturnRequest.order_id == order_id))
            ret = ret_res.scalar_one_or_none()
            assert ret is not None
            assert ret.customer_id == c1_id
            assert ret.ticket_id is not None

            tkt_res = await session.execute(select(SupportTicket).where(SupportTicket.id == ret.ticket_id))
            tkt = tkt_res.scalar_one_or_none()
            assert tkt is not None
            assert tkt.category == "Return Request"
            assert "[Melted chocolate]" in tkt.description

    # 2. Request rejected after 30 minutes
    async def test_return_rejected_after_30_minutes(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=800.0,
                subtotal=800.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=3),
                delivered_at=now - timedelta(minutes=35),  # 35 min > 30 min window
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        payload = {
            "reason": "Damaged product",
            "description": "The box was torn and damaged.",
        }
        res = await authenticated_client.post(f"/api/v1/orders/{order_id}/return", json=payload)
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "expired" in detail.lower() or "30 minutes" in detail.lower()

    # 3. Request rejected for undelivered or cancelled order
    async def test_return_rejected_for_undelivered_order(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order_shipped = Order(
                user_id=c1_id,
                total=500.0,
                subtotal=500.0,
                status="Shipped",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=5),
            )
            order_cancelled = Order(
                user_id=c1_id,
                total=600.0,
                subtotal=600.0,
                status="Cancelled",
                payment_method="Cash on Delivery",
                payment_status="CANCELLED",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=6),
            )
            session.add_all([order_shipped, order_cancelled])
            await session.commit()
            await session.refresh(order_shipped)
            await session.refresh(order_cancelled)
            shipped_id = order_shipped.id
            cancelled_id = order_cancelled.id

        # Try to return shipped order
        res1 = await authenticated_client.post(
            f"/api/v1/orders/{shipped_id}/return",
            json={"reason": "Damaged product", "description": "Package damaged on road"}
        )
        assert res1.status_code == 400
        assert "delivered" in res1.json()["detail"].lower()

        # Try to return cancelled order
        res2 = await authenticated_client.post(
            f"/api/v1/orders/{cancelled_id}/return",
            json={"reason": "Damaged product", "description": "Package damaged on road"}
        )
        assert res2.status_code == 400
        assert "delivered" in res2.json()["detail"].lower()

    # 4. Customer attempting to return another customer's order
    async def test_customer_cannot_return_another_customers_order(self, authenticated_client: AsyncClient):
        _, c2_id, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c2_id,  # Belongs to Customer 2
                total=1200.0,
                subtotal=1200.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer Two", "street": "99 Palm Ave", "city": "Mumbai", "state": "Maharashtra", "zip": "400001", "phone": "9123456789"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Customer 1 attempts to return Customer 2's order
        payload = {
            "reason": "Missing item",
            "description": "Item was missing from package.",
        }
        res = await authenticated_client.post(f"/api/v1/orders/{order_id}/return", json=payload)
        assert res.status_code in (404, 403)

    # 5. Missing description or invalid reason rejection
    async def test_missing_description_or_invalid_reason(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=950.0,
                subtotal=950.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Missing reason
        res1 = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "", "description": "Something was wrong."}
        )
        assert res1.status_code == 400
        assert "reason" in res1.json()["detail"].lower()

        # Invalid reason (not in the 6 allowed reasons)
        res2 = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Changed my mind", "description": "Don't want it anymore"}
        )
        assert res2.status_code == 400
        assert "reason" in res2.json()["detail"].lower()

        # Description too short (< 5 chars)
        res3 = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Damaged product", "description": "Bad"}
        )
        assert res3.status_code == 400
        assert "description" in res3.json()["detail"].lower()

    # 6. Invalid or oversized photo upload
    async def test_invalid_photo_upload(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=1100.0,
                subtotal=1100.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Unsupported file extension (.exe or .pdf)
        fake_exe = io.BytesIO(b"MZ\x90\x00\x03\x00\x00\x00")
        files = {"photo": ("malicious.exe", fake_exe, "application/octet-stream")}
        data = {"reason": "Damaged product", "description": "Damaged box upon arrival"}
        res = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            data=data,
            files=files,
        )
        assert res.status_code == 400
        assert "file" in res.json()["detail"].lower() or "extension" in res.json()["detail"].lower() or "format" in res.json()["detail"].lower()

        # Oversized file (> 5MB)
        oversized = io.BytesIO(b"0" * (6 * 1024 * 1024))
        files_oversized = {"photo": ("evidence.jpg", oversized, "image/jpeg")}
        res_over = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            data=data,
            files=files_oversized,
        )
        assert res_over.status_code == 400
        assert "size" in res_over.json()["detail"].lower()

    # 7. Duplicate return request handling
    async def test_duplicate_return_request_prevention(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=750.0,
                subtotal=750.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        payload = {"reason": "Packaging issue", "description": "The seal was broken."}
        # First submission
        res1 = await authenticated_client.post(f"/api/v1/orders/{order_id}/return", json=payload)
        assert res1.status_code == 200

        # Second submission (duplicate)
        res2 = await authenticated_client.post(f"/api/v1/orders/{order_id}/return", json=payload)
        assert res2.status_code == 400
        assert "already" in res2.json()["detail"].lower()

    # 8. Unauthorized support status updates
    async def test_unauthorized_status_update(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=550.0,
                subtotal=550.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Submit valid return
        await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Wrong product delivered", "description": "Received dark chocolate instead of milk chocolate."}
        )

        async with TestSessionLocal() as session:
            ret = (await session.execute(select(ReturnRequest).where(ReturnRequest.order_id == order_id))).scalar_one()
            ret_id = ret.id

        # Customer attempts to update status via admin endpoint
        res = await authenticated_client.put(
            f"/api/v1/admin/returns/{ret_id}/status",
            json={"status": "Approved", "admin_notes": "Self approved"}
        )
        assert res.status_code == 403

    # 9. Admin can update status (Approved -> order status Returned, Rejected -> order status Delivered)
    async def test_admin_status_update_approved_and_rejected(self, client: AsyncClient):
        c1_id, _, admin_id = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=1800.0,
                subtotal=1800.0,
                status="Delivered",
                payment_method="Online Payment",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Create return request directly or via service
        from app.services.return_service import ReturnService
        async with TestSessionLocal() as session:
            usr = await session.get(User, c1_id)
            svc = ReturnService(session)
            ret = await svc.create_return_request(
                order_id=order_id,
                user=usr,
                reason="Damaged product",
                description="Chocolate was completely melted and box broken.",
            )
            ret_id = ret.id

        # Authenticate as Admin
        admin_client = await self._get_admin_client(client, admin_id)

        # GET /api/v1/admin/returns
        res_list = await admin_client.get("/api/v1/admin/returns")
        assert res_list.status_code == 200
        returns_data = res_list.json()
        assert any(r["id"] == ret_id for r in returns_data)

        # PUT /api/v1/admin/returns/{id}/status -> Approved
        res_approve = await admin_client.put(
            f"/api/v1/admin/returns/{ret_id}/status",
            json={"status": "Approved", "admin_notes": "Evidence verified, return approved."}
        )
        assert res_approve.status_code == 200
        assert res_approve.json()["status"] == "Approved"

        # Check Order status updated to 'Returned'
        async with TestSessionLocal() as session:
            order_db = await session.get(Order, order_id)
            assert order_db.status == "Returned"

        # PUT /api/v1/admin/returns/{id}/status -> Rejected
        res_reject = await admin_client.put(
            f"/api/v1/admin/returns/{ret_id}/status",
            json={"status": "Rejected", "admin_notes": "Return rejected per policy."}
        )
        assert res_reject.status_code == 200
        assert res_reject.json()["status"] == "Rejected"

        # Check Order status reverts/stays at 'Delivered'
        async with TestSessionLocal() as session:
            order_db2 = await session.get(Order, order_id)
            assert order_db2.status == "Delivered"

    # 10. Customer can view their return request details and list
    async def test_customer_view_returns(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=990.0,
                subtotal=990.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=10),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Submit return
        await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Missing item", "description": "Gift box was missing 2 truffles."}
        )

        # GET /api/v1/orders/{order_id}/return
        res_ord = await authenticated_client.get(f"/api/v1/orders/{order_id}/return")
        assert res_ord.status_code == 200
        assert res_ord.json()["reason"] == "Missing item"

        # GET /api/v1/returns (list of all returns for customer)
        res_list = await authenticated_client.get("/api/v1/returns")
        assert res_list.status_code == 200
        assert len(res_list.json()) >= 1
        assert any(r["order_id"] == order_id for r in res_list.json())

    # 11. Helper to get superadmin client
    async def _get_superadmin_client(self, client: AsyncClient):
        import secrets
        async with TestSessionLocal() as session:
            res = await session.execute(select(User).where(User.email == "superadmin@chovique.com"))
            sa = res.scalar_one_or_none()
            if not sa:
                sa = User(
                    email="superadmin@chovique.com",
                    full_name="Super Admin User",
                    role="superadmin",
                    hashed_password=hash_password("SuperSecret123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(sa)
                await session.commit()
                await session.refresh(sa)
            sa_id = str(sa.id)

        token = create_access_token(sa_id)
        csrf = secrets.token_hex(16)
        client.cookies.set("access_token", token)
        client.cookies.set("csrf_token", csrf)
        client.headers["Authorization"] = f"Bearer {token}"
        client.headers["x-csrf-token"] = csrf
        return client

    # 12. Helper to set return policy
    async def _set_return_policy(self, client: AsyncClient, enabled: bool = True, value: int = 30, unit: str = "minutes", photo_required: bool = False):
        from app.repositories.platform_settings_repository import PlatformSettingsRepository
        async with TestSessionLocal() as session:
            repo = PlatformSettingsRepository(session)
            await repo.update({
                "return_requests_enabled": enabled,
                "return_window_value": value,
                "return_window_unit": unit,
                "return_photo_required": photo_required,
            })

    # 13. Public policy endpoint test
    async def test_get_return_policy_endpoint(self, authenticated_client: AsyncClient):
        await self._set_return_policy(authenticated_client, enabled=True, value=30, unit="minutes", photo_required=False)
        res = await authenticated_client.get("/api/v1/returns/policy")
        assert res.status_code == 200
        data = res.json()
        assert data["return_requests_enabled"] is True
        assert data["return_window_value"] == 30
        assert data["return_window_unit"] == "minutes"
        assert data["return_window_seconds"] == 1800.0
        assert data["return_photo_required"] is False

    # 14. Dynamic return window shortened (15m) and extended (45m)
    async def test_dynamic_return_window_shortened_and_extended(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        # 1. Order delivered 20 minutes ago
        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=1200.0,
                subtotal=1200.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=20),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Under 15-minute window: window has expired
        await self._set_return_policy(authenticated_client, enabled=True, value=15, unit="minutes", photo_required=False)
        res_expired = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Damaged product", "description": "Package arrived damaged."}
        )
        assert res_expired.status_code == 400
        assert "The return request window has expired" in res_expired.json()["detail"]
        assert "15 minutes" in res_expired.json()["detail"]

        # Superadmin extends window to 45 minutes: submission succeeds immediately!
        await self._set_return_policy(authenticated_client, enabled=True, value=45, unit="minutes", photo_required=False)
        res_success = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Damaged product", "description": "Package arrived damaged."}
        )
        assert res_success.status_code == 200
        assert res_success.json()["status"] == "Return Requested"
        assert res_success.json()["return_request"]["status"] == "Pending"

    # 15. Dynamic unit switching between hours and days
    async def test_dynamic_unit_switching_hours_and_days(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        # Order 1 delivered 75 minutes ago
        async with TestSessionLocal() as session:
            order1 = Order(
                user_id=c1_id,
                total=850.0,
                subtotal=850.0,
                status="Delivered",
                payment_method="UPI",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=2),
                delivered_at=now - timedelta(minutes=75),
            )
            session.add(order1)
            await session.commit()
            await session.refresh(order1)
            order1_id = order1.id

        # Set window to 2 hours
        await self._set_return_policy(authenticated_client, enabled=True, value=2, unit="hours", photo_required=False)
        res1 = await authenticated_client.post(
            f"/api/v1/orders/{order1_id}/return",
            json={"reason": "Melted chocolate", "description": "Bars melted during transit."}
        )
        assert res1.status_code == 200
        assert res1.json()["status"] == "Return Requested"
        assert res1.json()["return_request"]["status"] == "Pending"

        # Order 2 delivered 2 days ago
        async with TestSessionLocal() as session:
            order2 = Order(
                user_id=c1_id,
                total=1500.0,
                subtotal=1500.0,
                status="Delivered",
                payment_method="UPI",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(days=3),
                delivered_at=now - timedelta(days=2),
            )
            session.add(order2)
            await session.commit()
            await session.refresh(order2)
            order2_id = order2.id

        # Set window to 3 days
        await self._set_return_policy(authenticated_client, enabled=True, value=3, unit="days", photo_required=False)
        res2 = await authenticated_client.post(
            f"/api/v1/orders/{order2_id}/return",
            json={"reason": "Wrong product delivered", "description": "Received dark chocolate instead of milk chocolate."}
        )
        assert res2.status_code == 200
        assert res2.json()["status"] == "Return Requested"
        assert res2.json()["return_request"]["status"] == "Pending"

    # 16. Return requests globally disabled
    async def test_return_requests_disabled_globally(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=650.0,
                subtotal=650.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=5),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Disable return requests
        await self._set_return_policy(authenticated_client, enabled=False, value=30, unit="minutes", photo_required=False)

        # Order details indicates return_requests_enabled = False and is_returnable = False
        res_order = await authenticated_client.get(f"/api/v1/orders/{order_id}")
        assert res_order.status_code == 200
        assert res_order.json()["is_returnable"] is False
        assert res_order.json()["return_requests_enabled"] is False

        # Attempt to submit return request -> 400
        res_sub = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Packaging issue", "description": "Outer box torn."}
        )
        assert res_sub.status_code == 400
        assert "Return requests are currently unavailable" in res_sub.json()["detail"]

        # Reset to default
        await self._set_return_policy(authenticated_client, enabled=True, value=30, unit="minutes", photo_required=False)

    # 17. Photo evidence requirement enforcement
    async def test_photo_evidence_required_enforcement(self, authenticated_client: AsyncClient):
        c1_id, _, _ = await self._setup_users()
        now = datetime.now(timezone.utc)

        async with TestSessionLocal() as session:
            order = Order(
                user_id=c1_id,
                total=950.0,
                subtotal=950.0,
                status="Delivered",
                payment_method="Cash on Delivery",
                payment_status="PAID",
                shipping_address={"name": "Customer One", "street": "42 Cocoa Lane", "city": "Bangalore", "state": "Karnataka", "zip": "560038", "phone": "9876543210"},
                created_at=now - timedelta(hours=1),
                delivered_at=now - timedelta(minutes=5),
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            order_id = order.id

        # Enforce photo requirement
        await self._set_return_policy(authenticated_client, enabled=True, value=30, unit="minutes", photo_required=True)

        # 1. Attempt to submit without photo -> 400
        res_no_photo = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            json={"reason": "Melted chocolate", "description": "Completely melted."}
        )
        assert res_no_photo.status_code == 400
        assert "Photo evidence is required" in res_no_photo.json()["detail"]

        # 2. Submit with valid photo multipart -> 200
        photo_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        files = {"photo": ("evidence.png", io.BytesIO(photo_bytes), "image/png")}
        data = {
            "reason": "Melted chocolate",
            "description": "Completely melted upon opening box.",
        }
        res_with_photo = await authenticated_client.post(
            f"/api/v1/orders/{order_id}/return",
            data=data,
            files=files,
        )
        assert res_with_photo.status_code == 200
        assert res_with_photo.json()["status"] == "Return Requested"
        assert res_with_photo.json()["return_request"]["status"] == "Pending"
        assert res_with_photo.json()["return_request"]["photo_url"] is not None

        # Reset to default
        await self._set_return_policy(authenticated_client, enabled=True, value=30, unit="minutes", photo_required=False)

    # 18. Superadmin authorization vs other roles for modifying settings
    async def test_superadmin_auth_for_settings(self, authenticated_client: AsyncClient):
        # 1. Regular customer attempting to modify settings -> 403 Forbidden
        update_payload = {
            "store_front_name": "Chovique Luxury Chocolates",
            "support_email": "support@chovique.com",
            "support_phone": "+91 83098 54870",
            "store_address": "Chovique HQ",
            "city": "Bangalore",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560038",
            "base_currency": "INR",
            "timezone": "Asia/Kolkata",
            "business_status": "active",
            "cod_enabled": True,
            "gst_rate": 18.0,
            "platform_fee": 0.0,
            "standard_shipping_charge": 50.0,
            "free_shipping_min_order": 500.0,
            "maximum_cod_order_value": 5000.0,
            "customer_registration_enabled": True,
            "guest_checkout_enabled": True,
            "minimum_order_value": 100.0,
            "order_cancellation_enabled": True,
            "cancellation_time_limit": 24,
            "return_refund_enabled": True,
            "return_requests_enabled": True,
            "return_window_value": 45,
            "return_window_unit": "minutes",
            "return_photo_required": True,
            "maintenance_mode": False,
            "admin_session_timeout": 60,
            "max_login_attempts": 5,
            "account_lockout_duration": 30,
        }
        res_cust = await authenticated_client.put(
            "/api/v1/superadmin/platform-settings",
            json=update_payload
        )
        assert res_cust.status_code in (401, 403)

        # 2. Regular admin attempting to modify settings -> 403 Forbidden
        _, _, adm_id = await self._setup_users()
        admin_client = await self._get_admin_client(authenticated_client, adm_id)
        res_adm = await admin_client.put(
            "/api/v1/superadmin/platform-settings",
            json=update_payload
        )
        assert res_adm.status_code == 403

        # 3. Superadmin successfully updates settings
        sa_client = await self._get_superadmin_client(authenticated_client)
        res_sa = await sa_client.put(
            "/api/v1/superadmin/platform-settings",
            json=update_payload
        )
        assert res_sa.status_code == 200
        sa_data = res_sa.json()
        assert sa_data["return_window_value"] == 45
        assert sa_data["return_photo_required"] is True

        # Reset to safe defaults
        await self._set_return_policy(authenticated_client, enabled=True, value=30, unit="minutes", photo_required=False)

