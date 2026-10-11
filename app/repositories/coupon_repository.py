import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.coupon import Coupon, CouponEligibilityRule, CouponProduct, CouponCategory


class CouponRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    def _parse_datetime(self, val, is_end_of_day: bool = False):
        if not val:
            return None
        if isinstance(val, datetime.datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        if isinstance(val, datetime.date):
            t = datetime.time(23, 59, 59) if is_end_of_day else datetime.time(0, 0, 0)
            return datetime.datetime.combine(val, t, tzinfo=timezone.utc)
        if isinstance(val, str):
            val_str = val.strip()
            if not val_str:
                return None
            if val_str.endswith("Z") or val_str.endswith("z"):
                val_str = val_str[:-1] + "+00:00"

            # 1. Check DD-MM-YYYY (e.g. 01-09-2026)
            import re
            if re.match(r"^\d{2}-\d{2}-\d{4}$", val_str):
                try:
                    dt = datetime.datetime.strptime(val_str, "%d-%m-%Y")
                    if is_end_of_day:
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # 2. Check DD/MM/YYYY (e.g. 01/09/2026)
            if re.match(r"^\d{2}/\d{2}/\d{4}$", val_str):
                try:
                    dt = datetime.datetime.strptime(val_str, "%d/%m/%Y")
                    if is_end_of_day:
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # 3. Check YYYY-MM-DD (e.g. 2026-09-01)
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val_str):
                try:
                    dt = datetime.datetime.strptime(val_str, "%Y-%m-%d")
                    if is_end_of_day:
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            # 4. Standard ISO format
            try:
                dt = datetime.datetime.fromisoformat(val_str)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

            # 5. Common formats (supports days, hours, and minutes)
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d"):
                try:
                    dt = datetime.datetime.strptime(val_str, fmt)
                    if is_end_of_day and fmt in ("%Y/%m/%d",):
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

            # 6. Fallback with dateutil
            try:
                from dateutil import parser
                dt = parser.parse(val_str, dayfirst=True)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass

        return None

    def _parse_expires_at(self, val):
        return self._parse_datetime(val, is_end_of_day=True)

    def _check_and_deactivate(self, coupon: Coupon) -> bool:
        if coupon and coupon.expires_at:
            now_utc = datetime.datetime.now(timezone.utc)
            exp = coupon.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if now_utc >= exp and coupon.is_active:
                coupon.is_active = False
                return True
        return False

    async def get_by_code(self, code: str) -> Coupon | None:
        result = await self.db.execute(
            select(Coupon)
            .options(
                selectinload(Coupon.rules),
                selectinload(Coupon.products),
                selectinload(Coupon.categories),
                selectinload(Coupon.usages),
            )
            .where(Coupon.code == code.upper())
        )
        coupon = result.scalar_one_or_none()
        if coupon and self._check_and_deactivate(coupon):
            await self.db.commit()
            await self.db.refresh(coupon)
        return coupon

    async def get_active_coupons(self) -> list[Coupon]:
        coupons = await self.get_all()
        return [c for c in coupons if c.is_active]

    async def get_all(self) -> list[Coupon]:
        result = await self.db.execute(
            select(Coupon)
            .options(
                selectinload(Coupon.rules),
                selectinload(Coupon.products),
                selectinload(Coupon.categories),
                selectinload(Coupon.usages),
            )
            .order_by(Coupon.created_at.desc())
        )
        coupons = list(result.scalars().all())
        updated = False
        for c in coupons:
            if self._check_and_deactivate(c):
                updated = True
        if updated:
            await self.db.commit()
            for c in coupons:
                await self.db.refresh(c)
        return coupons

    async def create(self, **kwargs) -> Coupon:
        code_clean = kwargs["code"].upper()
        existing = await self.get_by_code(code_clean)
        if existing:
            raise ValueError(f"A coupon with code '{code_clean}' already exists.")

        kwargs["code"] = code_clean

        has_expiry_arg = any(k in kwargs for k in ("expires_at", "expiryDate", "expiry_date", "expiresAt", "endDate", "end_date"))
        expires_raw = (
            kwargs.pop("expires_at", None)
            or kwargs.pop("expiryDate", None)
            or kwargs.pop("expiry_date", None)
            or kwargs.pop("expiresAt", None)
            or kwargs.pop("endDate", None)
            or kwargs.pop("end_date", None)
        )
        if has_expiry_arg:
            kwargs["expires_at"] = self._parse_expires_at(expires_raw) if expires_raw else None

        has_start_arg = any(k in kwargs for k in ("start_at", "startDate", "start_date", "startAt", "begin_date"))
        start_raw = (
            kwargs.pop("start_at", None)
            or kwargs.pop("startDate", None)
            or kwargs.pop("start_date", None)
            or kwargs.pop("startAt", None)
            or kwargs.pop("begin_date", None)
        )
        if has_start_arg:
            kwargs["start_at"] = self._parse_datetime(start_raw, is_end_of_day=False) if start_raw else None

        eligibility_rule = kwargs.pop("eligibility_rule", None)
        eligibility_value = kwargs.pop("eligibility_value", None)
        applicability = kwargs.pop("applicability", None)
        applicable_ids = kwargs.pop("applicable_ids", [])

        # Filter kwargs to only columns present on Coupon ORM model
        valid_kwargs = {k: v for k, v in kwargs.items() if hasattr(Coupon, k)}

        coupon = Coupon(**valid_kwargs)
        self._check_and_deactivate(coupon)
        self.db.add(coupon)
        await self.db.flush()

        if eligibility_rule and eligibility_rule != "ALL_USERS":
            rule = CouponEligibilityRule(
                coupon_id=coupon.id,
                rule_type=eligibility_rule,
                rule_value=str(eligibility_value) if eligibility_value else None,
            )
            self.db.add(rule)

        if applicability in ("SPECIFIC_PRODUCTS", "PRODUCTS") and applicable_ids:
            for pid in applicable_ids:
                if pid:
                    self.db.add(CouponProduct(coupon_id=coupon.id, product_id=str(pid)))
        elif applicability in ("SPECIFIC_CATEGORIES", "CATEGORIES") and applicable_ids:
            for cid in applicable_ids:
                if cid:
                    self.db.add(CouponCategory(coupon_id=coupon.id, category_id=str(cid)))

        await self.db.commit()
        return await self.get_by_code(code_clean)

    async def update(self, code: str, **kwargs) -> Coupon | None:
        kwargs.pop("code", None)
        coupon = await self.get_by_code(code)
        if not coupon:
            return None
        
        has_expiry_arg = any(k in kwargs for k in ("expires_at", "expiryDate", "expiry_date", "expiresAt", "endDate", "end_date"))
        expires_raw = (
            kwargs.pop("expires_at", None)
            or kwargs.pop("expiryDate", None)
            or kwargs.pop("expiry_date", None)
            or kwargs.pop("expiresAt", None)
            or kwargs.pop("endDate", None)
            or kwargs.pop("end_date", None)
        )
        if has_expiry_arg:
            kwargs["expires_at"] = self._parse_expires_at(expires_raw) if expires_raw else None

        has_start_arg = any(k in kwargs for k in ("start_at", "startDate", "start_date", "startAt", "begin_date"))
        start_raw = (
            kwargs.pop("start_at", None)
            or kwargs.pop("startDate", None)
            or kwargs.pop("start_date", None)
            or kwargs.pop("startAt", None)
            or kwargs.pop("begin_date", None)
        )
        if has_start_arg:
            kwargs["start_at"] = self._parse_datetime(start_raw, is_end_of_day=False) if start_raw else None

        kwargs.pop("eligibility_rule", None)
        kwargs.pop("eligibility_value", None)
        kwargs.pop("applicability", None)
        kwargs.pop("applicable_ids", None)

        for key, value in kwargs.items():
            if hasattr(coupon, key):
                setattr(coupon, key, value)
                
        self._check_and_deactivate(coupon)
        await self.db.commit()
        await self.db.refresh(coupon)
        return coupon

    async def delete(self, code: str) -> bool:
        coupon = await self.get_by_code(code)
        if not coupon:
            return False
        await self.db.delete(coupon)
        await self.db.commit()
        return True

    async def count(self) -> int:
        from sqlalchemy import func
        result = await self.db.execute(select(func.count()).select_from(Coupon))
        return result.scalar() or 0
