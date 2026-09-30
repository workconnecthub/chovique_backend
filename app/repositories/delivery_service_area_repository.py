from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.delivery_service_area import DeliveryServiceArea


class DeliveryServiceAreaRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_pincode(self, pincode: str) -> Optional[DeliveryServiceArea]:
        clean_pin = str(pincode or "").strip()
        result = await self.db.execute(
            select(DeliveryServiceArea).where(DeliveryServiceArea.pincode == clean_pin)
        )
        return result.scalar_one_or_none()

    async def get_active_by_pincode(self, pincode: str) -> Optional[DeliveryServiceArea]:
        clean_pin = str(pincode or "").strip()
        result = await self.db.execute(
            select(DeliveryServiceArea).where(
                DeliveryServiceArea.pincode == clean_pin,
                DeliveryServiceArea.active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_all(
        self,
        active_only: bool = False,
        mode: Optional[str] = None,
    ) -> List[DeliveryServiceArea]:
        stmt = select(DeliveryServiceArea)
        if active_only:
            stmt = stmt.where(DeliveryServiceArea.active == True)
        if mode:
            stmt = stmt.where(DeliveryServiceArea.delivery_mode == mode.upper())
        stmt = stmt.order_by(DeliveryServiceArea.city.asc(), DeliveryServiceArea.pincode.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, area_id: str) -> Optional[DeliveryServiceArea]:
        result = await self.db.execute(
            select(DeliveryServiceArea).where(DeliveryServiceArea.id == area_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> DeliveryServiceArea:
        if "pincode" in kwargs:
            kwargs["pincode"] = str(kwargs["pincode"]).strip()
        if "delivery_mode" in kwargs:
            kwargs["delivery_mode"] = str(kwargs["delivery_mode"]).upper()

        area = DeliveryServiceArea(**kwargs)
        self.db.add(area)
        await self.db.commit()
        await self.db.refresh(area)
        return area

    async def update(self, area_id: str, **kwargs) -> Optional[DeliveryServiceArea]:
        area = await self.get_by_id(area_id)
        if not area:
            return None

        if "pincode" in kwargs and kwargs["pincode"] is not None:
            kwargs["pincode"] = str(kwargs["pincode"]).strip()
        if "delivery_mode" in kwargs and kwargs["delivery_mode"] is not None:
            kwargs["delivery_mode"] = str(kwargs["delivery_mode"]).upper()

        for k, v in kwargs.items():
            if hasattr(area, k) and v is not None:
                setattr(area, k, v)

        await self.db.commit()
        await self.db.refresh(area)
        return area

    async def delete(self, area_id: str) -> bool:
        area = await self.get_by_id(area_id)
        if not area:
            return False
        await self.db.delete(area)
        await self.db.commit()
        return True
