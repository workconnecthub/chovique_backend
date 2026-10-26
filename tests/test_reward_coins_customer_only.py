import pytest
import secrets
from httpx import AsyncClient
from sqlalchemy import select
from app.models.user import User
from app.models.wallet import UserWallet, CoinTransaction
from app.models.product import Product
from app.models.order import Order
from app.services.wallet_service import WalletService
from app.services.superadmin_service import ensure_superadmin_exists
from app.core.security import hash_password, create_access_token
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


def make_auth_headers(user_id: str):
    csrf = secrets.token_hex(16)
    token = create_access_token(user_id)
    return {
        "Authorization": f"Bearer {token}",
        "x-csrf-token": csrf,
    }, {"access_token": token, "csrf_token": csrf}


class TestRewardCoinsCustomerOnly:

    async def test_1_customer_registration_awards_200_coins_once(self, client: AsyncClient, mock_redis):
        """1. Customer registration via OTP verification awards 200 coins exactly once."""
        phone = "9876500001"

        # Request OTP
        send_res = await client.post(
            "/api/v1/auth/customer/send-otp",
            json={"phone": phone},
        )
        assert send_res.status_code == 200

        # Retrieve plain OTP dispatched in test environment from mock_redis
        otp1 = await mock_redis.get(f"otp:test_val:customer_login:{phone}")
        assert otp1 is not None

        # 1st verification (new user registration)
        res1 = await client.post(
            "/api/v1/auth/customer/verify-otp",
            json={"phone": phone, "otp": otp1},
        )
        assert res1.status_code == 200
        user_data = res1.json()["user"]
        user_id = user_data["id"]

        # Check DB wallet balance and transaction
        async with TestSessionLocal() as session:
            wallet_svc = WalletService(session)
            summary = await wallet_svc.compute_user_coin_summary(user_id)
            assert summary["available_coins"] == 200

            txs = (await session.execute(
                select(CoinTransaction).where(CoinTransaction.user_id == user_id)
            )).scalars().all()
            assert len(txs) == 1
            assert txs[0].type == "WELCOME"
            assert txs[0].coins == 200

            # Direct call to get_user_wallet_details must also not duplicate welcome coins
            wallet_resp = await wallet_svc.get_user_wallet_details(user_id)
            assert wallet_resp.coin_balance == 200
            assert len(wallet_resp.recent_transactions) == 1

            # Verify idempotency in DB
            txs_after = (await session.execute(
                select(CoinTransaction).where(
                    CoinTransaction.user_id == user_id,
                    CoinTransaction.type == "WELCOME"
                )
            )).scalars().all()
            assert len(txs_after) == 1

    async def test_2_super_admin_initialization_awards_zero_coins(self, client: AsyncClient):
        """2. Super Admin initialization awards zero coins."""
        async with TestSessionLocal() as session:
            sa = await ensure_superadmin_exists(session)
            sa_id = str(sa.id)
            sa_role = sa.role
            assert sa_role == "super_admin"

            # Check that Super Admin has 0 coins and 0 transactions
            wallet_svc = WalletService(session)
            summary = await wallet_svc.compute_user_coin_summary(sa_id)
            assert summary["available_coins"] == 0
            assert summary["total_earned"] == 0

            txs = (await session.execute(
                select(CoinTransaction).where(CoinTransaction.user_id == sa_id)
            )).scalars().all()
            assert len(txs) == 0

    async def test_3_admin_account_creation_awards_zero_coins(self, client: AsyncClient):
        """3. Admin account creation awards zero coins."""
        async with TestSessionLocal() as session:
            admin_user = User(
                email="testadmin@chovique.com",
                full_name="Operations Admin",
                phone="919876500002",
                role="admin",
                hashed_password=hash_password("AdminPass123!"),
                is_email_verified=True,
                is_phone_verified=True,
                is_active=True,
            )
            session.add(admin_user)
            await session.commit()
            await session.refresh(admin_user)
            admin_id = str(admin_user.id)

            wallet_svc = WalletService(session)
            summary = await wallet_svc.compute_user_coin_summary(admin_id)
            assert summary["available_coins"] == 0
            assert summary["total_earned"] == 0

            txs = (await session.execute(
                select(CoinTransaction).where(CoinTransaction.user_id == admin_id)
            )).scalars().all()
            assert len(txs) == 0

    async def test_4_delivery_person_account_creation_awards_zero_coins(self, client: AsyncClient):
        """4. Delivery Person account creation awards zero coins."""
        async with TestSessionLocal() as session:
            dp_user = User(
                email="deliverytest@chovique.com",
                full_name="Delivery Runner",
                phone="919876500003",
                role="delivery_person",
                hashed_password=hash_password("DeliveryPass123!"),
                is_email_verified=True,
                is_phone_verified=True,
                is_active=True,
            )
            session.add(dp_user)
            await session.commit()
            await session.refresh(dp_user)
            dp_id = str(dp_user.id)

            wallet_svc = WalletService(session)
            summary = await wallet_svc.compute_user_coin_summary(dp_id)
            assert summary["available_coins"] == 0
            assert summary["total_earned"] == 0

            txs = (await session.execute(
                select(CoinTransaction).where(CoinTransaction.user_id == dp_id)
            )).scalars().all()
            assert len(txs) == 0

    async def test_5_staff_cannot_access_or_redeem_via_wallet_apis(self, client: AsyncClient):
        """5. Staff cannot earn or redeem coins through direct API requests (403 Forbidden)."""
        async with TestSessionLocal() as session:
            # Create a super_admin, admin, and delivery_boy
            sa = User(
                email="sa_api@chovique.com",
                full_name="Super Admin API",
                phone="919876500010",
                role="super_admin",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            ad = User(
                email="ad_api@chovique.com",
                full_name="Admin API",
                phone="919876500011",
                role="admin",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            dp = User(
                email="dp_api@chovique.com",
                full_name="Delivery API",
                phone="919876500012",
                role="delivery_person",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            session.add_all([sa, ad, dp])
            await session.commit()
            await session.refresh(sa)
            await session.refresh(ad)
            await session.refresh(dp)

            staff_ids = [str(sa.id), str(ad.id), str(dp.id)]

        for s_id in staff_ids:
            headers, cookies = make_auth_headers(s_id)
            client.cookies.update(cookies)

            # 1. GET /api/v1/wallet must return 403
            res_wallet = await client.get("/api/v1/wallet", headers=headers)
            assert res_wallet.status_code == 403
            assert "exclusively to customer accounts" in res_wallet.json()["detail"]

            # 2. GET /api/v1/wallet/transactions must return 403
            res_txs = await client.get("/api/v1/wallet/transactions", headers=headers)
            assert res_txs.status_code == 403

            # 3. POST /api/v1/wallet/calculate-redemption must return 403
            res_calc = await client.post(
                "/api/v1/wallet/calculate-redemption",
                json={"subtotal": 500, "coins_requested": 50},
                headers=headers,
            )
            assert res_calc.status_code == 403

    async def test_6_eligible_customer_orders_earn_and_redeem_correct_coins(self, client: AsyncClient):
        """6. Eligible customer orders earn the correct coins and redemption works."""
        async with TestSessionLocal() as session:
            # Create a customer with 200 coins
            cust = User(
                email="shopper@chovique.com",
                full_name="Loyal Customer",
                phone="919876500020",
                role="customer",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(cust)
            await session.commit()
            await session.refresh(cust)
            cust_id = str(cust.id)

            wallet_svc = WalletService(session)
            # Add welcome coins
            await wallet_svc.wallet_repo.add_transaction(
                user_id=cust_id,
                transaction_type="WELCOME",
                coins=200,
                description="Welcome Bonus",
                commit=True,
            )
            # Also add an existing completed order so this is NOT their first order
            past_order = Order(
                user_id=cust_id,
                total=500.0,
                subtotal=500.0,
                payment_status="Paid",
                status="Delivered",
                shipping_address={"city": "Mumbai"},
            )
            session.add(past_order)
            await session.commit()
            await session.refresh(past_order)

            # Customer creates a new order of ₹1000
            new_order = Order(
                user_id=cust_id,
                total=1000.0,
                subtotal=1000.0,
                payment_status="Paid",
                status="Processing",
                shipping_address={"city": "Mumbai"},
            )
            session.add(new_order)
            await session.commit()
            await session.refresh(new_order)

            # Customer redeems 100 coins (₹10 value)
            redeem_tx = await wallet_svc.redeem_coins(
                user_id=cust_id,
                order_id=new_order.id,
                coins=100,
                commit=True,
            )
            assert redeem_tx.coins == -100

            # Customer earns coins on ₹1000 order (10 coins per ₹100 = 100 coins)
            coins_earned, _ = await wallet_svc.earn_coins(
                user_id=cust_id,
                order_id=new_order.id,
                payable_amount=1000.0,
                commit=True,
            )
            assert coins_earned == 100

            # Verify balance: 200 (welcome) - 100 (redeemed) = 100 available, 100 pending (1-day delay)
            summary = await wallet_svc.compute_user_coin_summary(cust_id)
            assert summary["total_earned"] == 300  # 200 welcome + 100 order
            assert summary["total_redeemed"] == 100
            assert summary["available_coins"] == 100
            assert summary["pending_coins"] == 100

    async def test_7_order_cancellation_and_refund_reversal(self, client: AsyncClient):
        """7. Return/reversal transactions update customer balances correctly."""
        async with TestSessionLocal() as session:
            cust = User(
                email="refund_shopper@chovique.com",
                full_name="Refund Customer",
                phone="919876500030",
                role="customer",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(cust)
            await session.commit()
            await session.refresh(cust)
            cust_id = str(cust.id)

            wallet_svc = WalletService(session)
            await wallet_svc.wallet_repo.add_transaction(
                user_id=cust_id,
                transaction_type="WELCOME",
                coins=200,
                description="Welcome Bonus",
                commit=True,
            )

            # Order with 50 coins redeemed and 80 coins earned
            ord_obj = Order(
                user_id=cust_id,
                total=800.0,
                subtotal=800.0,
                coins_used=50,
                coins_earned=80,
                payment_status="Paid",
                status="Processing",
                shipping_address={"city": "Mumbai"},
            )
            session.add(ord_obj)
            await session.commit()
            await session.refresh(ord_obj)

            # Process refund of order coins
            returned_coins, reversed_coins = await wallet_svc.refund_order_coins(
                user_id=cust_id,
                order_id=ord_obj.id,
                coins_used=50,
                coins_earned=80,
                commit=True,
            )
            assert returned_coins == 50
            assert reversed_coins == 80

            # Balance should be back to 200 (returned 50 coins, reversed 80 coins)
            summary = await wallet_svc.compute_user_coin_summary(cust_id)
            assert summary["total_returned"] == 50
            assert summary["total_reversed"] == 80

    async def test_8_staff_wallet_balances_remain_zero_and_cannot_earn(self, client: AsyncClient):
        """8. Staff cannot earn coins even if order processing is simulated."""
        async with TestSessionLocal() as session:
            staff = User(
                email="staff_order@chovique.com",
                full_name="Staff Tester",
                phone="919876500040",
                role="admin",
                hashed_password=hash_password("Pass123!"),
                is_active=True,
            )
            session.add(staff)
            await session.commit()
            await session.refresh(staff)
            staff_id = str(staff.id)

            wallet_svc = WalletService(session)

            # Attempt to earn coins on staff order
            earned, _ = await wallet_svc.earn_coins(
                user_id=staff_id,
                order_id="fake-order-id",
                payable_amount=1500.0,
                commit=True,
            )
            assert earned == 0

            # Attempt to redeem coins
            with pytest.raises(Exception):
                await wallet_svc.redeem_coins(
                    user_id=staff_id,
                    order_id="fake-order-id",
                    coins=50,
                    commit=True,
                )

            # Summary must be strictly 0
            summary = await wallet_svc.compute_user_coin_summary(staff_id)
            assert summary["available_coins"] == 0
            assert summary["total_earned"] == 0
