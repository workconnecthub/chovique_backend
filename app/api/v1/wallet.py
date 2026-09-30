from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.wallet import (
    UserWalletResponse,
    CoinTransactionResponse,
    PaginatedCoinTransactionsResponse,
    CalculateRedemptionRequest,
    CalculateRedemptionResponse,
)
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/wallet", tags=["Wallet & Rewards"])


@router.get("", response_model=UserWalletResponse, summary="Get current user's wallet balance and reward details")
async def get_wallet(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WalletService(db)
    return await service.get_user_wallet_details(current_user.id)


@router.get("/transactions", response_model=PaginatedCoinTransactionsResponse, summary="Get transaction history with filtering and pagination")
async def get_transactions(
    type: Optional[str] = Query(None, description="ALL, EARN, REDEEM, ADJUSTMENT"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    offset: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WalletService(db)
    calc_offset = offset if offset is not None else (page - 1) * limit
    txs = await service.wallet_repo.get_transactions(current_user.id, type_filter=type, limit=limit, offset=calc_offset)
    total = await service.wallet_repo.count_transactions(current_user.id, type_filter=type)
    pages = max(1, (total + limit - 1) // limit) if limit > 0 else 1
    actual_page = (calc_offset // limit) + 1 if limit > 0 else page
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    settings = await service.get_reward_settings()
    delay_hours = getattr(settings, "credit_delay_hours", 24) or 24

    items = []
    for t in txs:
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

        items.append(
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

    return {
        "items": items,
        "total": total,
        "page": actual_page,
        "pages": pages,
        "limit": limit
    }


@router.post("/calculate-redemption", response_model=CalculateRedemptionResponse, summary="Calculate allowed coin redemption for order preview")
async def calculate_redemption(
    payload: CalculateRedemptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = WalletService(db)
    return await service.calculate_redemption(
        user_id=current_user.id,
        subtotal=payload.subtotal,
        coupon_discount=payload.coupon_discount,
        coins_requested=payload.coins_to_use,
    )
