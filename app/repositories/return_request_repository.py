from typing import Optional, List
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.return_request import ReturnRequest


class ReturnRequestRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> ReturnRequest:
        obj = ReturnRequest(**kwargs)
        self.db.add(obj)
        await self.db.commit()
        await self.db.refresh(obj)
        return obj

    async def get_by_id(self, return_id: str) -> Optional[ReturnRequest]:
        stmt = select(ReturnRequest).where(ReturnRequest.id == return_id)
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_by_order_id(self, order_id: str) -> Optional[ReturnRequest]:
        stmt = select(ReturnRequest).where(ReturnRequest.order_id == order_id)
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def get_by_customer_id(self, customer_id: str) -> List[ReturnRequest]:
        stmt = (
            select(ReturnRequest)
            .where(ReturnRequest.customer_id == customer_id)
            .order_by(desc(ReturnRequest.created_at))
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_all(self) -> List[ReturnRequest]:
        stmt = select(ReturnRequest).order_by(desc(ReturnRequest.created_at))
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def update(self, return_obj: ReturnRequest) -> ReturnRequest:
        self.db.add(return_obj)
        await self.db.commit()
        await self.db.refresh(return_obj)
        return return_obj
