from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==========================================================
    # Create User
    # ==========================================================

    async def create(self, **kwargs) -> User:
        user = User(**kwargs)

        self.db.add(user)

        await self.db.commit()

        await self.db.refresh(user)

        if user.role not in ("admin", "superadmin", "super_admin"):
            try:
                from app.services.notification_service import NotificationService
                await NotificationService(self.db).notify_new_customer(user.id, user.full_name or user.email)
            except Exception:
                pass

        return user

    # ==========================================================
    # Get By Email
    # ==========================================================

    async def get_by_email(self, email: str) -> User | None:

        result = await self.db.execute(
            select(User).where(User.email == email)
        )

        return result.scalar_one_or_none()

    # ==========================================================
    # Get By Phone
    # ==========================================================

    @staticmethod
    def _get_phone_lookup_variants(phone: str) -> list[str]:
        if not phone:
            return []
        raw = str(phone).strip()
        variants = {raw}
        try:
            from app.integrations.msg91 import parse_and_normalize_phone
            e164, nat, _ = parse_and_normalize_phone(raw)
            variants.add(e164)
            variants.add(nat)
            variants.add(e164.lstrip("+"))
            if len(nat) == 10:
                variants.add(f"0{nat}")
                variants.add(f"+91 {nat[:5]} {nat[5:]}")
                variants.add(f"+91 {nat}")
                variants.add(f"{nat[:5]} {nat[5:]}")
                variants.add(f"+91-{nat[:5]}-{nat[5:]}")
                variants.add(f"+91-{nat}")
                variants.add(f"{nat[:5]}-{nat[5:]}")
        except Exception:
            import re
            clean_digits = re.sub(r"\D", "", raw)
            if clean_digits:
                variants.add(clean_digits)
                nat = clean_digits[-10:]
                variants.add(nat)
                variants.add(f"+91{nat}")
                variants.add(f"91{nat}")
                variants.add(f"0{nat}")
                if len(nat) == 10:
                    variants.add(f"+91 {nat[:5]} {nat[5:]}")
                    variants.add(f"+91 {nat}")
                    variants.add(f"{nat[:5]} {nat[5:]}")
                    variants.add(f"+91-{nat[:5]}-{nat[5:]}")
                    variants.add(f"+91-{nat}")
                    variants.add(f"{nat[:5]}-{nat[5:]}")
        return list(variants)

    @classmethod
    def _build_phone_filter_conditions(cls, phone: str):
        from sqlalchemy import or_, func
        import re
        variants = cls._get_phone_lookup_variants(phone)
        if not variants:
            return None
        conditions = [User.phone.in_(variants)]
        clean_digits = re.sub(r"\D", "", str(phone))[-10:]
        if clean_digits and len(clean_digits) == 10:
            cleaned_db_phone = func.regexp_replace(User.phone, r"\D", "", "g")
            conditions.append(cleaned_db_phone.in_([clean_digits, f"91{clean_digits}", f"0{clean_digits}"]))
        return or_(*conditions)

    async def get_by_phone(self, phone: str) -> User | None:
        from sqlalchemy import case
        filter_cond = self._build_phone_filter_conditions(phone)
        if filter_cond is None:
            return None
        stmt = (
            select(User)
            .where(filter_cond)
            .order_by(
                case(
                    (User.role == "superadmin", 1),
                    (User.role == "super_admin", 1),
                    (User.role == "admin", 2),
                    (User.role == "delivery_boy", 3),
                    (User.role == "delivery_person", 3),
                    (User.role == "customer", 4),
                    else_=5,
                ),
                User.is_active.desc(),
                User.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_by_phone(self, phone: str) -> list[User]:
        from sqlalchemy import case
        filter_cond = self._build_phone_filter_conditions(phone)
        if filter_cond is None:
            return []
        stmt = (
            select(User)
            .where(filter_cond)
            .order_by(
                case(
                    (User.role == "superadmin", 1),
                    (User.role == "super_admin", 1),
                    (User.role == "admin", 2),
                    (User.role == "delivery_boy", 3),
                    (User.role == "delivery_person", 3),
                    (User.role == "customer", 4),
                    else_=5,
                ),
                User.is_active.desc(),
                User.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_staff_by_phone(self, phone: str) -> User | None:
        from sqlalchemy import case
        filter_cond = self._build_phone_filter_conditions(phone)
        if filter_cond is None:
            return None
        staff_roles = ["superadmin", "super_admin", "admin", "delivery_boy", "delivery_person"]
        stmt = (
            select(User)
            .where(filter_cond, User.role.in_(staff_roles))
            .order_by(
                case(
                    (User.role == "superadmin", 1),
                    (User.role == "super_admin", 1),
                    (User.role == "admin", 2),
                    (User.role == "delivery_boy", 3),
                    (User.role == "delivery_person", 3),
                    else_=4,
                ),
                User.is_active.desc(),
                User.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_by_phone_and_role(self, phone: str, role: str) -> User | None:
        from app.schemas.auth import normalize_staff_role
        canonical_role = role
        try:
            canonical_role = normalize_staff_role(role)
        except Exception:
            pass
        filter_cond = self._build_phone_filter_conditions(phone)
        if filter_cond is None:
            return None
        target_roles = {role, canonical_role}
        if "delivery_boy" in target_roles or "delivery_person" in target_roles:
            target_roles.update(["delivery_boy", "delivery_person"])
        if "superadmin" in target_roles or "super_admin" in target_roles:
            target_roles.update(["superadmin", "super_admin"])
        allowed = ["superadmin", "super_admin", "admin", "delivery_boy", "delivery_person", "customer"]
        valid_roles = [r for r in target_roles if r in allowed]
        if not valid_roles:
            return None
        stmt = (
            select(User)
            .where(filter_cond, User.role.in_(valid_roles))
            .order_by(
                User.is_active.desc(),
                User.created_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    # ==========================================================
    # Get By ID
    # ==========================================================

    async def get_by_id(self, user_id: str) -> User | None:

        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )

        return result.scalar_one_or_none()

    # ==========================================================
    # Get By Google ID
    # ==========================================================

    async def get_by_google_id(
        self,
        google_id: str,
    ) -> User | None:

        result = await self.db.execute(
            select(User).where(User.google_id == google_id)
        )

        return result.scalar_one_or_none()

    # ==========================================================
    # Verify Email
    # ==========================================================

    async def verify_email(
        self,
        user_id: str,
    ) -> None:

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_email_verified=True)
        )

        await self.db.commit()

    # ==========================================================
    # Update Password
    # ==========================================================

    async def update_password(
        self,
        user_id: str,
        hashed_password: str,
    ) -> None:

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(hashed_password=hashed_password)
        )

        await self.db.commit()

    # ==========================================================
    # Update Google ID
    # ==========================================================

    async def update_google_id(
        self,
        user_id: str,
        google_id: str,
    ) -> None:

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(google_id=google_id)
        )

        await self.db.commit()

    async def update_google_data(
        self,
        user_id: str,
        google_id: str,
        avatar_url: str | None = None,
    ) -> None:

        values = {"google_id": google_id}
        if avatar_url is not None:
            values["avatar_url"] = avatar_url

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(**values)
        )

        await self.db.commit()

    # ==========================================================
    # Update Last Login
    # ==========================================================

    async def update_last_login(
        self,
        user_id: str,
        last_login_at,
    ) -> None:

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=last_login_at)
        )

        await self.db.commit()

    # ==========================================================
    # Deactivate User
    # ==========================================================

    async def deactivate(
        self,
        user_id: str,
    ) -> None:

        await self.db.execute(
            update(User)
            .where(User.id == user_id)
            .values(is_active=False)
        )

        await self.db.commit()

    # ==========================================================
    # Update Profile
    # ==========================================================

    async def update_profile(
        self,
        user_id: str,
        **kwargs,
    ) -> User | None:

        if kwargs:
            await self.db.execute(
                update(User)
                .where(User.id == user_id)
                .values(**kwargs)
            )
            await self.db.commit()

        return await self.get_by_id(user_id)

    # ==========================================================
    # Count Customers
    # ==========================================================

    async def count_customers(self) -> int:
        from sqlalchemy import select, func
        result = await self.db.execute(
            select(func.count(User.id)).where(User.role == "customer")
        )
        return result.scalar_one_or_none() or 0

    async def list_customers_paginated(
        self,
        search: str | None = None,
        status_filter: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[User], int]:
        from sqlalchemy import select, func, or_
        query = select(User).where(User.role == "customer")

        if status_filter and status_filter.upper() == 'ACTIVE':
            query = query.where(User.is_active == True)
        elif status_filter and status_filter.upper() == 'INACTIVE':
            query = query.where(User.is_active == False)

        if search and search.strip():
            like = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(User.full_name).like(like),
                    func.lower(User.email).like(like),
                    func.lower(User.phone).like(like),
                )
            )

        count_query = select(func.count()).select_from(query.subquery())
        count_res = await self.db.execute(count_query)
        total = count_res.scalar_one_or_none() or 0

        offset = (page - 1) * limit
        data_query = query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        data_res = await self.db.execute(data_query)
        users = list(data_res.scalars().all())

        return users, total