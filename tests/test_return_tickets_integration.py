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
class TestReturnTicketsIntegration:

    async def _setup_users(self):
        """Helper to create customer1, customer2, and admin users."""
        async with TestSessionLocal() as session:
            # Customer 1
            res1 = await session.execute(select(User).where(User.email == "cust1_ticket@example.com"))
            c1 = res1.scalar_one_or_none()
            if not c1:
                c1 = User(
                    email="cust1_ticket@example.com",
                    full_name="Alice Customer",
                    phone="9876543210",
                    role="customer",
                    hashed_password=hash_password("Pass123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(c1)

            # Customer 2
            res2 = await session.execute(select(User).where(User.email == "cust2_ticket@example.com"))
            c2 = res2.scalar_one_or_none()
            if not c2:
                c2 = User(
                    email="cust2_ticket@example.com",
                    full_name="Bob Customer",
                    phone="9123456780",
                    role="customer",
                    hashed_password=hash_password("Pass123!"),
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                session.add(c2)

            # Admin
            res3 = await session.execute(select(User).where(User.email == "admin_ticket@chovique.com"))
            adm = res3.scalar_one_or_none()
            if not adm:
                adm = User(
                    email="admin_ticket@chovique.com",
                    full_name="Head Admin",
                    phone="9999999999",
                    role="admin",
                    hashed_password=hash_password("AdminPass123!"),
                    is_email_verified=True,
                    is_active=True,
                )
                session.add(adm)

            await session.commit()
            await session.refresh(c1)
            await session.refresh(c2)
            await session.refresh(adm)
            return c1, c2, adm

    async def _create_delivered_order(self, user_id: str, minutes_ago: int = 10, total: float = 1250.0):
        """Create a delivered order for testing return requests."""
        now_utc = datetime.now(timezone.utc)
        delivery_time = now_utc - timedelta(minutes=minutes_ago)
        async with TestSessionLocal() as session:
            order = Order(
                user_id=user_id,
                total=total,
                subtotal=total - 50.0,
                shipping=50.0,
                status="Delivered",
                payment_status="PAID",
                payment_method="UPI",
                shipping_address={
                    "name": "Alice Customer",
                    "house_number": "Flat 402",
                    "street": "Park Avenue",
                    "area": "Bandra West",
                    "city": "Mumbai",
                    "district": "Mumbai Suburban",
                    "state": "Maharashtra",
                    "zip": "400050",
                    "pincode": "400050",
                },
                shipping_name="Alice Customer",
                shipping_phone="9876543210",
                delivered_at=delivery_time,
            )
            session.add(order)
            await session.commit()
            await session.refresh(order)
            return order

    async def test_all_six_return_reasons_create_return_tickets_automatically(self, client: AsyncClient):
        """Verify that every supported return reason creates a SupportTicket visible in PostgreSQL."""
        c1, _, admin = await self._setup_users()
        c1_token = create_access_token(str(c1.id))
        admin_token = create_access_token(str(admin.id))

        reasons = [
            "Damaged product",
            "Melted chocolate",
            "Wrong product delivered",
            "Missing item",
            "Packaging issue",
            "Other issue",
        ]

        for idx, reason in enumerate(reasons):
            order = await self._create_delivered_order(c1.id, minutes_ago=5, total=800.0 + idx * 100)

            # Customer submits return request
            data = {
                "reason": reason,
                "description": f"Testing ticket creation for return reason: {reason}.",
            }
            res = await client.post(
                f"/api/v1/orders/{order.id}/return",
                headers={"Authorization": f"Bearer {c1_token}"},
                json=data,
            )
            assert res.status_code == 200, f"Failed for reason {reason}: {res.text}"
            order_json = res.json()
            ret_json = order_json.get("return_request")
            assert ret_json is not None, f"return_request missing in response: {order_json}"
            return_id = ret_json["id"]
            ticket_id = ret_json.get("ticket_id")
            assert ticket_id is not None, "ticket_id should be returned on return request"

            # Check that SupportTicket exists in PostgreSQL
            async with TestSessionLocal() as session:
                st_res = await session.execute(select(SupportTicket).where(SupportTicket.id == ticket_id))
                ticket = st_res.scalar_one_or_none()
                assert ticket is not None, "SupportTicket was not persisted in DB"
                assert ticket.category == "Return Request"
                assert ticket.return_request_id == return_id
                assert ticket.order_id == order.id
                assert ticket.status == "Pending"

        # Check that Admin GET /api/v1/admin/tickets returns all of them
        admin_res = await client.get(
            "/api/v1/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_res.status_code == 200
        tickets_list = admin_res.json()
        assert len(tickets_list) >= 6

        return_tickets = [t for t in tickets_list if t["category"] == "Return Request"]
        assert len(return_tickets) >= 6
        found_reasons = {t.get("returnReason") or t.get("return_reason") for t in return_tickets}
        for r in reasons:
            assert r in found_reasons, f"Expected reason {r} to be displayed in admin tickets"

    async def test_return_ticket_information_fields(self, client: AsyncClient):
        """Verify that all required ticket information is populated for Admin Dashboard complaints."""
        c1, _, admin = await self._setup_users()
        c1_token = create_access_token(str(c1.id))
        admin_token = create_access_token(str(admin.id))

        order = await self._create_delivered_order(c1.id, minutes_ago=10, total=1999.50)

        # Submit with a mock image evidence
        image_content = b"fake_jpeg_image_data_test_content"
        files = {
            "photo": ("evidence.jpg", io.BytesIO(image_content), "image/jpeg"),
        }
        data = {
            "reason": "Melted chocolate",
            "description": "Chocolates completely melted upon delivery in hot weather.",
        }
        create_res = await client.post(
            f"/api/v1/orders/{order.id}/return",
            headers={"Authorization": f"Bearer {c1_token}"},
            data=data,
            files=files,
        )
        assert create_res.status_code == 200, create_res.text
        created_json = create_res.json()
        ret_json = created_json.get("return_request")
        assert ret_json is not None
        ticket_id = ret_json["ticket_id"]

        # Admin fetches tickets
        admin_res = await client.get(
            "/api/v1/admin/tickets",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_res.status_code == 200
        matching = [t for t in admin_res.json() if t["id"] == ticket_id]
        assert len(matching) == 1
        tkt = matching[0]

        # Verify all required fields from Requirement 2
        assert tkt["id"] == ticket_id
        assert tkt["orderId"] == order.id or tkt["order_id"] == order.id
        assert tkt["customerName"] == c1.full_name
        assert tkt["customerEmail"] == c1.email or tkt["customer_email"] == c1.email
        assert tkt["customerPhone"] == c1.phone or tkt["customer_phone"] == c1.phone
        assert tkt["orderAmount"] == 1999.50 or tkt["order_amount"] == 1999.50
        assert tkt["currency"] == "₹"
        assert tkt["paymentMethod"] == "UPI" or tkt["payment_method"] == "UPI"
        assert tkt["deliveryAddress"] is not None or tkt["delivery_address"] is not None
        assert tkt["deliveredAt"] is not None or tkt["delivered_at"] is not None
        assert tkt["returnReason"] == "Melted chocolate" or tkt["return_reason"] == "Melted chocolate"
        assert "Melted chocolate" in tkt["description"]
        assert tkt["photoUrl"] is not None or tkt["photo_url"] is not None
        assert tkt["status"] == "Pending"
        assert tkt["returnRequestId"] is not None or tkt["return_request_id"] is not None

    async def test_admin_review_resolution_and_assigned_tracking(self, client: AsyncClient):
        """Verify admin can change status to Under Review, Approved, Rejected, Resolved and updates assigned admin."""
        c1, _, admin = await self._setup_users()
        c1_token = create_access_token(str(c1.id))
        admin_token = create_access_token(str(admin.id))

        order = await self._create_delivered_order(c1.id, minutes_ago=5, total=1450.0)
        data = {
            "reason": "Damaged product",
            "description": "Outer seal was broken and chocolate box damaged.",
        }
        res = await client.post(
            f"/api/v1/orders/{order.id}/return",
            headers={"Authorization": f"Bearer {c1_token}"},
            json=data,
        )
        assert res.status_code == 200, res.text
        ticket_id = res.json()["return_request"]["ticket_id"]

        # 1. Admin moves to "Under Review"
        status_res1 = await client.post(
            f"/api/v1/admin/tickets/{ticket_id}/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "Under Review", "admin_notes": "Inspecting warehouse shipment dispatch log."},
        )
        assert status_res1.status_code == 200
        t1 = status_res1.json()
        assert t1["status"] == "Under Review"
        assert t1["adminNotes"] == "Inspecting warehouse shipment dispatch log."
        assert t1["assignedAdmin"] == admin.full_name or t1["assigned_admin"] == admin.full_name

        # 2. Admin moves to "Approved"
        status_res2 = await client.post(
            f"/api/v1/admin/tickets/{ticket_id}/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "Approved", "admin_notes": "Return approved. Pickup initiated."},
        )
        assert status_res2.status_code == 200
        t2 = status_res2.json()
        assert t2["status"] == "Approved"

        # Check DB sync on ReturnRequest and Order
        async with TestSessionLocal() as session:
            rr_res = await session.execute(select(ReturnRequest).where(ReturnRequest.ticket_id == ticket_id))
            ret_req = rr_res.scalar_one()
            assert ret_req.status == "Approved"
            assert ret_req.admin_notes == "Return approved. Pickup initiated."

            ord_res = await session.execute(select(Order).where(Order.id == order.id))
            ord_obj = ord_res.scalar_one()
            assert ord_obj.status == "Returned"
            # Crucial: Approving return must NOT alter payment_status to REFUNDED automatically!
            assert ord_obj.payment_status == "PAID", "Payment must remain separate from return review approval"

        # 3. Admin moves to "Resolved"
        status_res3 = await client.post(
            f"/api/v1/admin/tickets/{ticket_id}/status",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"status": "Resolved", "admin_notes": "Issue fully resolved with customer."},
        )
        assert status_res3.status_code == 200
        t3 = status_res3.json()
        assert t3["status"] == "Resolved"

    async def test_duplicate_submission_blocked_and_no_duplicate_tickets(self, client: AsyncClient):
        """Verify re-submitting return request for the same order does not create duplicate tickets."""
        c1, _, _ = await self._setup_users()
        c1_token = create_access_token(str(c1.id))

        order = await self._create_delivered_order(c1.id, minutes_ago=5, total=999.0)
        data = {
            "reason": "Missing item",
            "description": "Only 3 out of 4 chocolate bars were present in package.",
        }

        # First submission
        res1 = await client.post(
            f"/api/v1/orders/{order.id}/return",
            headers={"Authorization": f"Bearer {c1_token}"},
            json=data,
        )
        assert res1.status_code == 200

        # Second submission
        res2 = await client.post(
            f"/api/v1/orders/{order.id}/return",
            headers={"Authorization": f"Bearer {c1_token}"},
            json=data,
        )
        assert res2.status_code == 400
        assert "already been submitted" in res2.json()["detail"].lower()

        # Verify only 1 ticket was created in DB for this order
        async with TestSessionLocal() as session:
            res_tickets = await session.execute(select(SupportTicket).where(SupportTicket.order_id == order.id))
            tickets = res_tickets.scalars().all()
            assert len(tickets) == 1

    async def test_unauthorized_user_blocked_from_admin_tickets(self, client: AsyncClient):
        """Verify unauthorized customer cannot access admin tickets endpoint."""
        c1, _, _ = await self._setup_users()
        c1_token = create_access_token(str(c1.id))

        # Customer tries to call admin tickets endpoint
        res = await client.get(
            "/api/v1/admin/tickets",
            headers={"Authorization": f"Bearer {c1_token}"},
        )
        assert res.status_code in (401, 403)

    async def test_customer_ticket_isolation(self, client: AsyncClient):
        """Verify customers can only view their own tickets via customer support endpoint."""
        c1, c2, _ = await self._setup_users()
        c1_token = create_access_token(str(c1.id))
        c2_token = create_access_token(str(c2.id))

        order1 = await self._create_delivered_order(c1.id, minutes_ago=5, total=500.0)
        data1 = {
            "reason": "Damaged product",
            "description": "Box was crushed during transit.",
        }
        res1 = await client.post(
            f"/api/v1/orders/{order1.id}/return",
            headers={"Authorization": f"Bearer {c1_token}"},
            json=data1,
        )
        assert res1.status_code == 200
        c1_ticket_id = res1.json()["return_request"]["ticket_id"]

        # Customer 2 checks their tickets
        c2_tickets_res = await client.get(
            "/api/v1/support/tickets",
            headers={"Authorization": f"Bearer {c2_token}"},
        )
        assert c2_tickets_res.status_code == 200
        c2_ticket_ids = [t["id"] for t in c2_tickets_res.json()]
        assert c1_ticket_id not in c2_ticket_ids, "Customer 2 must not see Customer 1's ticket"
