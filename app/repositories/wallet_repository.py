import uuid
from typing import List, Optional
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.wallet import UserWallet, CoinTransaction


class WalletRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_wallet(self, user_id: str) -> UserWallet:
        result = await self.db.execute(
            select(UserWallet).where(UserWallet.user_id == user_id)
        )
        wallet = result.scalar_one_or_none()

        if not wallet:
            wallet = UserWallet(user_id=user_id, coin_balance=0)
            self.db.add(wallet)
            await self.db.flush()

        return wallet

    async def get_by_user_id(self, user_id: str) -> UserWallet:
        return await self.get_or_create_wallet(user_id)

    async def add_transaction(
        self,
        user_id: str,
        transaction_type: str,
        coins: int,
        description: Optional[str] = None,
        order_id: Optional[str] = None,
        commit: bool = False,
    ) -> CoinTransaction:
        wallet = await self.get_or_create_wallet(user_id)
        
        # Update balance safely
        new_balance = wallet.coin_balance + coins
        if new_balance < 0:
            new_balance = 0
        wallet.coin_balance = new_balance
        self.db.add(wallet)

        transaction = CoinTransaction(
            user_id=user_id,
            order_id=order_id,
            type=transaction_type,
            coins=coins,
            description=description,
        )
        self.db.add(transaction)

        if commit:
            await self.db.commit()
            await self.db.refresh(wallet)
            await self.db.refresh(transaction)
        else:
            await self.db.flush()

        return transaction

    async def get_transactions(
        self, user_id: str, type_filter: Optional[str] = None, limit: int = 50, offset: int = 0
    ) -> List[CoinTransaction]:
        query = select(CoinTransaction).where(CoinTransaction.user_id == user_id)
        if type_filter and type_filter.upper() != "ALL":
            query = query.where(CoinTransaction.type == type_filter.upper())
        query = query.order_by(CoinTransaction.created_at.desc()).offset(offset).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_transactions(
        self, user_id: str, type_filter: Optional[str] = None
    ) -> int:
        query = select(func.count(CoinTransaction.id)).where(CoinTransaction.user_id == user_id)
        if type_filter and type_filter.upper() != "ALL":
            query = query.where(CoinTransaction.type == type_filter.upper())
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def get_order_transactions(
        self, order_id: str
    ) -> List[CoinTransaction]:
        result = await self.db.execute(
            select(CoinTransaction)
            .where(CoinTransaction.order_id == order_id)
        )
        return list(result.scalars().all())


