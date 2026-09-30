from typing import List, Optional
from pydantic import BaseModel, ConfigDict
from datetime import datetime


class CoinTransactionResponse(BaseModel):
    id: str
    user_id: str
    order_id: Optional[str] = None
    type: str
    coins: int
    description: Optional[str] = None
    created_at: datetime
    status: Optional[str] = "AVAILABLE"  # "PENDING" or "AVAILABLE"
    is_pending: bool = False
    unlocks_at: Optional[datetime] = None
    delay_hours: Optional[int] = 24

    model_config = ConfigDict(from_attributes=True)


class PaginatedCoinTransactionsResponse(BaseModel):
    items: List[CoinTransactionResponse]
    total: int
    page: int
    pages: int
    limit: int



class RewardSettingsSchema(BaseModel):
    reward_system_enabled: bool = True
    spend_per_coin: float = 10.0      # ₹10 spent = 1 coin earned (10 coins per ₹100)
    coins_per_rupee: float = 10.0     # 10 coins = ₹1 discount
    max_redemption_percentage: float = 20.0  # Max 20% of subtotal can be paid with coins
    welcome_coins: int = 200          # Account creation reward = 200 coins
    first_order_coins: int = 200     # First order bonus = 200 coins
    credit_delay_hours: int = 24      # 24-hour waiting period for order coins
    per_order_coins_fixed: int = 0    # Fixed coins given per order (if 0, relies on spend_per_coin)


class UserWalletResponse(BaseModel):
    id: str
    user_id: str
    coin_balance: int
    available_coins: int = 0
    pending_coins: int = 0
    rupee_value: float
    settings: RewardSettingsSchema
    recent_transactions: List[CoinTransactionResponse] = []

    model_config = ConfigDict(from_attributes=True)


class AdminCustomerRewardStat(BaseModel):
    user_id: str
    customer_name: str
    customer_email: str
    available_coins: int
    pending_coins: int
    total_coins_earned: int
    total_coins_redeemed: int
    total_coins_returned: int
    total_coins_reversed: int
    first_order_bonus_status: str


class AdminCoinTransactionItem(BaseModel):
    id: str
    customer_name: str
    customer_email: str
    coins: int
    transaction_type: str
    status: str
    reason: str
    order_id: Optional[str] = None
    created_at: str
    available_at: Optional[str] = None


class CalculateRedemptionRequest(BaseModel):
    subtotal: float
    coupon_discount: float = 0.0
    coins_to_use: int = 0


class CalculateRedemptionResponse(BaseModel):
    user_balance: int
    coins_requested: int
    allowed_coins: int
    coin_discount: float
    max_usable_coins: int
    max_coin_discount: float
    message: str


