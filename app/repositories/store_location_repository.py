from typing import Optional, List
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.store_location import StoreLocation


class StoreLocationRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all(self, active_only: bool = False) -> List[StoreLocation]:
        stmt = select(StoreLocation)
        if active_only:
            stmt = stmt.where(StoreLocation.active == True)
        stmt = stmt.order_by(StoreLocation.is_primary.desc(), StoreLocation.created_at.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, store_id: str) -> Optional[StoreLocation]:
        result = await self.db.execute(
            select(StoreLocation).where(StoreLocation.id == store_id)
        )
        return result.scalar_one_or_none()

    async def get_primary_store(self) -> Optional[StoreLocation]:
        result = await self.db.execute(
            select(StoreLocation).where(StoreLocation.is_primary == True, StoreLocation.active == True)
        )
        store = result.scalar_one_or_none()
        if not store:
            # Fallback to first active store if no explicit primary flag set
            res2 = await self.db.execute(
                select(StoreLocation).where(StoreLocation.active == True).order_by(StoreLocation.created_at.asc())
            )
            store = res2.scalars().first()
        return store

    async def create(self, **kwargs) -> StoreLocation:
        if kwargs.get("is_primary"):
            # Unset primary flag on other stores
            await self.db.execute(
                update(StoreLocation).values(is_primary=False)
            )

        store = StoreLocation(**kwargs)
        self.db.add(store)
        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def update(self, store_id: str, **kwargs) -> Optional[StoreLocation]:
        store = await self.get_by_id(store_id)
        if not store:
            return None

        if kwargs.get("is_primary"):
            await self.db.execute(
                update(StoreLocation).where(StoreLocation.id != store_id).values(is_primary=False)
            )

        for k, v in kwargs.items():
            if hasattr(store, k) and v is not None:
                setattr(store, k, v)

        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def set_primary(self, store_id: str) -> Optional[StoreLocation]:
        store = await self.get_by_id(store_id)
        if not store:
            return None

        await self.db.execute(
            update(StoreLocation).values(is_primary=False)
        )
        store.is_primary = True
        store.active = True
        await self.db.commit()
        await self.db.refresh(store)
        return store

    async def delete(self, store_id: str) -> bool:
        store = await self.get_by_id(store_id)
        if not store:
            return False
        # Soft delete / deactivate
        store.active = False
        await self.db.commit()
        return True
