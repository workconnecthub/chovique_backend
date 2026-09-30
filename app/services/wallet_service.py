import json
import logging
import math
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.wallet_repository import WalletRepository
from app.repositories.site_config_repository import SiteConfigRepository
from app.schemas.wallet import (
    RewardSettingsSchema,
    UserWalletResponse,
    CoinTransactionResponse,
    CalculateRedemptionResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_REWARD_SETTINGS = {
    "reward_system_enabled": True,
    "spend_per_coin": 10.0,
    "coins_per_rupee": 10.0,
    "max_redemption_percentage": 20.0,
    "welcome_coins": 200,
    "first_order_coins": 200,
    "credit_delay_hours": 24,
    "per_order_coins_fixed": 0,
}


class WalletService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.wallet_repo = WalletRepository(db)
        self.site_config_repo = SiteConfigRepository(db)

    async def get_reward_settings(self) -> RewardSettingsSchema:
        raw = await self.site_config_repo.get("reward_settings")
        if not raw:
            return RewardSettingsSchema(**DEFAULT_REWARD_SETTINGS)

        try:
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, dict):
                data = raw
            else:
                data = DEFAULT_REWARD_SETTINGS
            merged = {**DEFAULT_REWARD_SETTINGS, **data}
            return RewardSettingsSchema(**merged)
        except Exception as e:
            logger.error(f"Error parsing reward settings: {e}")
            return RewardSettingsSchema(**DEFAULT_REWARD_SETTINGS)

    async def update_reward_settings(self, settings: RewardSettingsSchema) -> RewardSettingsSchema:
        dump = settings.model_dump()
        await self.site_config_repo.set("reward_settings", dump)
        return settings

    async def compute_user_coin_summary(self, user_id: str):
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        settings = await self.get_reward_settings()
        delay_hours = getattr(settings, "credit_delay_hours", 24) or 24

        txs = await self.wallet_repo.get_transactions(user_id, limit=500)

        available = 0
        pending = 0
        earned = 0
        redeemed = 0
        returned = 0
        reversed_amt = 0

        for t in txs:
            t_type = (t.type or "").upper()
            t_dt = t.created_at
            if t_dt and t_dt.tzinfo is None:
                t_dt = t_dt.replace(tzinfo=timezone.utc)

            is_welcome = t_type in ("WELCOME", "WELCOME_BONUS", "ACCOUNT_CREATION", "REGISTRATION_BONUS") or "welcome" in (t.description or "").lower()
            is_order_earn = (t_type in ("EARN", "ORDER_REWARD", "FIRST_ORDER_BONUS") or bool(t.order_id)) and not is_welcome

            if is_welcome:
                if t.coins > 0:
                    earned += t.coins
                available += t.coins
            elif is_order_earn:
                if t.coins > 0:
                    earned += t.coins
                if t_dt and (now_utc < t_dt + timedelta(hours=delay_hours)):
                    pending += max(0, t.coins)
                else:
                    available += t.coins
            elif t_type in ("REFUND", "RETURN", "COIN_RETURN"):
                if t.coins > 0:
                    returned += t.coins
                available += t.coins
            elif t_type in ("REDEEM", "COIN_REDEMPTION"):
                if t.coins < 0:
                    redeemed += abs(t.coins)
                available += t.coins
            elif t_type in ("ADJUSTMENT", "REVERSAL", "COIN_REVERSAL"):
                if t.coins < 0:
                    reversed_amt += abs(t.coins)
                available += t.coins
            else:
                if t.coins > 0:
                    earned += t.coins
                available += t.coins

        available_coins = max(0, available)
        pending_coins = max(0, pending)

        # Sync wallet balance
        wallet = await self.wallet_repo.get_or_create_wallet(user_id)
        if wallet.coin_balance != available_coins:
            wallet.coin_balance = available_coins
            self.db.add(wallet)
            await self.db.flush()

        return {
            "available_coins": available_coins,
            "pending_coins": pending_coins,
            "total_earned": earned,
            "total_redeemed": redeemed,
            "total_returned": returned,
            "total_reversed": reversed_amt,
        }

    async def get_user_wallet_details(self, user_id: str) -> UserWalletResponse:
        from datetime import datetime, timezone, timedelta
        now_utc = datetime.now(timezone.utc)
        wallet = await self.wallet_repo.get_or_create_wallet(user_id)
        settings = await self.get_reward_settings()
        transactions = await self.wallet_repo.get_transactions(user_id, limit=50)

        # Auto-grant 200 Welcome Coins for any registered customer who has no welcome bonus yet
        has_welcome = any(
            (t.type or "").upper() in ("WELCOME", "WELCOME_BONUS", "ACCOUNT_CREATION")
            or "welcome" in (t.description or "").lower()
            for t in transactions
        )
        if not has_welcome and settings.reward_system_enabled and settings.welcome_coins > 0:
            await self.wallet_repo.add_transaction(
                user_id=user_id,
                transaction_type="WELCOME",
                coins=settings.welcome_coins,
                description="Welcome Bonus — Registration Reward",
                commit=True,
            )
            transactions = await self.wallet_repo.get_transactions(user_id, limit=50)

        summary = await self.compute_user_coin_summary(user_id)
        delay_hours = getattr(settings, "credit_delay_hours", 24) or 24

        formatted_txs = []
        for t in transactions:
            t_type = (t.type or "").upper()
            t_dt = t.created_at
            if t_dt and t_dt.tzinfo is None:
                t_dt = t_dt.replace(tzinfo=timezone.utc)

            is_welcome = t_type in ("WELCOME", "WELCOME_BONUS", "ACCOUNT_CREATION") or "welcome" in (t.description or "").lower()
            is_order_earn = (t_type in ("EARN", "ORDER_REWARD", "FIRST_ORDER_BONUS") or bool(t.order_id)) and not is_welcome

            status = "AVAILABLE"
            is_pending = False
            unlocks_at = None

            if is_order_earn and t_dt:
                target_unlock = t_dt + timedelta(hours=delay_hours)
                if now_utc < target_unlock:
                    status = "PENDING"
                    is_pending = True
                    unlocks_at = target_unlock

            formatted_txs.append(
                CoinTransactionResponse(
                    id=t.id,
                    user_id=t.user_id,
                    order_id=t.order_id,
                    type="WELCOME" if is_welcome else t.type,
                    coins=t.coins,
                    description=t.description,
                    created_at=t.created_at,
                    status=status,
                    is_pending=is_pending,
                    unlocks_at=unlocks_at,
                    delay_hours=delay_hours,
                )
            )

        rupee_val = round(summary["available_coins"] / settings.coins_per_rupee, 2) if settings.coins_per_rupee > 0 else 0.0

        return UserWalletResponse(
            id=wallet.id,
            user_id=wallet.user_id,
            coin_balance=summary["available_coins"],
            available_coins=summary["available_coins"],
            pending_coins=summary["pending_coins"],
            rupee_value=rupee_val,
            settings=settings,
            recent_transactions=formatted_txs,
        )

    async def calculate_redemption(
        self,
        user_id: str,
        subtotal: float,
        coupon_discount: float = 0.0,
        coins_requested: int = 0,
    ) -> CalculateRedemptionResponse:
        settings = await self.get_reward_settings()
        summary = await self.compute_user_coin_summary(user_id)
        available_balance = summary["available_coins"]

        if not settings.reward_system_enabled:
            return CalculateRedemptionResponse(
                user_balance=available_balance,
                coins_requested=coins_requested,
                allowed_coins=0,
                coin_discount=0.0,
                max_usable_coins=0,
                max_coin_discount=0.0,
                message="Reward system is currently disabled.",
            )

        eligible_subtotal = max(0.0, subtotal - coupon_discount)
        max_discount_allowed = eligible_subtotal * (settings.max_redemption_percentage / 100.0)
        max_usable_coins = math.floor(max_discount_allowed * settings.coins_per_rupee)

        # Cap coins by available balance and allowed threshold
        allowed_coins = min(available_balance, coins_requested, max_usable_coins)
        if allowed_coins < 0:
            allowed_coins = 0

        coin_discount = round(allowed_coins / settings.coins_per_rupee, 2) if settings.coins_per_rupee > 0 else 0.0

        if allowed_coins <= 0:
            if available_balance <= 0:
                msg = "Available reward coins are insufficient for redemption on this order."
            elif max_usable_coins <= 0:
                msg = "Reward coins cannot be applied to this order."
            elif available_balance < coins_requested:
                msg = f"Requested {coins_requested} coins, but available balance is {available_balance} coins."
            else:
                msg = "Available reward coins are insufficient for redemption on this order."
        else:
            msg = f"{allowed_coins} coins applied for Rs. {coin_discount} discount."
            if coins_requested > allowed_coins:
                if available_balance < coins_requested:
                    msg = f"Requested {coins_requested} coins, but available balance is {available_balance} coins."
                else:
                    msg = f"Maximum allowed coins for this order is {max_usable_coins} ({settings.max_redemption_percentage}% of order value)."

        return CalculateRedemptionResponse(
            user_balance=available_balance,
            coins_requested=coins_requested,
            allowed_coins=allowed_coins,
            coin_discount=coin_discount,
            max_usable_coins=max_usable_coins,
            max_coin_discount=round(max_discount_allowed, 2),
            message=msg,
        )

    async def redeem_coins(
        self,
        user_id: str,
        order_id: str,
        coins: int,
        commit: bool = False,
    ):
        if coins <= 0:
            return None
        tx = await self.wallet_repo.add_transaction(
            user_id=user_id,
            transaction_type="REDEEM",
            coins=-abs(coins),
            description=f"Redeemed on Order #{order_id}",
            order_id=order_id,
            commit=commit,
        )

        try:
            from app.repositories.notification_repository import NotificationRepository
            notif_repo = NotificationRepository(self.db)
            await notif_repo.create(
                user_id=user_id,
                type="reward",
                title="Reward Coins Redeemed",
                message=f"You redeemed {abs(coins)} Reward Coins on your order.",
                text=f"You redeemed {abs(coins)} Reward Coins on your order.",
                related_entity_type="wallet",
                related_entity_id=order_id,
                reference_id=order_id,
                commit=commit,
            )
        except Exception as err:
            logger.debug(f"Failed to create coin redeemed notification: {err}")

        return tx

    async def earn_coins(
        self,
        user_id: str,
        order_id: str,
        payable_amount: float,
        commit: bool = False,
    ):
        settings = await self.get_reward_settings()
        if not settings.reward_system_enabled:
            return 0, []

        from app.models.order import Order
        from app.models.wallet import CoinTransaction
        from sqlalchemy import select, func

        # Check existing non-cancelled orders for user (excluding current order)
        order_count = await self.db.scalar(
            select(func.count(Order.id)).where(
                Order.user_id == user_id,
                Order.id != order_id,
                Order.status.notin_(["Cancelled", "CANCELLED"])
            )
        ) or 0

        # Check if first order bonus was ever awarded for this user
        existing_first_order = await self.db.scalar(
            select(func.count(CoinTransaction.id)).where(
                CoinTransaction.user_id == user_id,
                CoinTransaction.type == "FIRST_ORDER_BONUS"
            )
        ) or 0

        total_coins = 0
        created_txs = []

        # 1. First Order Bonus (200 Coins) if user has no previous completed orders and bonus wasn't awarded
        if order_count == 0 and existing_first_order == 0 and settings.first_order_coins > 0:
            tx_bonus = await self.wallet_repo.add_transaction(
                user_id=user_id,
                transaction_type="FIRST_ORDER_BONUS",
                coins=settings.first_order_coins,
                description=f"First Order Bonus #{order_id}",
                order_id=order_id,
                commit=False,
            )
            total_coins += settings.first_order_coins
            created_txs.append(tx_bonus)

        # 2. Regular Order Reward (10 Coins per ₹100 order value)
        order_coins = 0
        if settings.spend_per_coin > 0 and payable_amount > 0:
            order_coins = math.floor(payable_amount / settings.spend_per_coin)
            if order_coins > 0:
                tx_reward = await self.wallet_repo.add_transaction(
                    user_id=user_id,
                    transaction_type="ORDER_REWARD",
                    coins=order_coins,
                    description=f"Order Reward #{order_id}",
                    order_id=order_id,
                    commit=False,
                )
                total_coins += order_coins
                created_txs.append(tx_reward)

        if total_coins > 0:
            try:
                from app.repositories.notification_repository import NotificationRepository
                notif_repo = NotificationRepository(self.db)
                await notif_repo.create(
                    user_id=user_id,
                    type="reward",
                    title="Reward Coins Earned",
                    message=f"You earned {total_coins} Reward Coins from your order. (Available after 24 hours)",
                    text=f"You earned {total_coins} Reward Coins from your order. (Available after 24 hours)",
                    related_entity_type="wallet",
                    related_entity_id=order_id,
                    reference_id=order_id,
                    commit=commit,
                )
            except Exception as err:
                logger.debug(f"Failed to create coin earned notification: {err}")

        if commit:
            await self.db.commit()

        return total_coins, created_txs

    async def refund_order_coins(
        self,
        user_id: str,
        order_id: str,
        coins_used: int,
        coins_earned: int,
        commit: bool = False,
    ):
        # Prevent duplicate refund/reversal
        existing = await self.wallet_repo.get_order_transactions(order_id)
        has_refund = any(t.type in ("REFUND", "RETURN", "COIN_RETURN", "ADJUSTMENT", "REVERSAL", "COIN_REVERSAL") for t in existing)
        if has_refund:
            return

        # Restore redeemed coins
        if coins_used > 0:
            await self.wallet_repo.add_transaction(
                user_id=user_id,
                transaction_type="COIN_RETURN",
                coins=coins_used,
                description=f"Returned used coins from Cancelled Order #{order_id}",
                order_id=order_id,
                commit=commit,
            )

        # Reverse earned coins
        if coins_earned > 0:
            await self.wallet_repo.add_transaction(
                user_id=user_id,
                transaction_type="COIN_REVERSAL",
                coins=-coins_earned,
                description=f"Reversed earned coins from Cancelled Order #{order_id}",
                order_id=order_id,
                commit=commit,
            )


