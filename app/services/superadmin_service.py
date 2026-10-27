import logging
from typing import Optional
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.integrations.msg91 import parse_and_normalize_phone
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def ensure_superadmin_exists(db: AsyncSession) -> Optional[User]:
    """
    Ensure the initial Super Admin account exists in PostgreSQL.

    Reads credentials from application configuration (SUPERADMIN_EMAIL,
    SUPERADMIN_PASSWORD, SUPERADMIN_PHONE).

    Behavior:
    - Normalizes email and phone number.
    - Idempotent: Checks if an account already exists with the normalized email,
      normalized phone number, or existing super admin roles ('super_admin', 'superadmin').
    - If found, safely preserves existing credentials and account data without resetting
      passwords or overwriting fields.
    - If not found, creates the account with role='super_admin', hashes the password
      using Argon2, marks verified, and commits to PostgreSQL.
    - Never stores plain-text passwords or overwrites on restarts.
    """
    admin_email = (settings.SUPERADMIN_EMAIL or "").strip().lower()
    admin_password = settings.SUPERADMIN_PASSWORD or ""
    admin_phone = (settings.SUPERADMIN_PHONE or "").strip()

    if not admin_email or not admin_password:
        logger.warning(
            "SUPERADMIN_EMAIL or SUPERADMIN_PASSWORD not configured. Skipping Super Admin seeding."
        )
        return None

    clean_phone = None
    if admin_phone:
        try:
            clean_phone, _, _ = parse_and_normalize_phone(admin_phone, default_country_code="+91")
        except Exception as e:
            logger.warning("Failed to normalize SUPERADMIN_PHONE '%s': %s", admin_phone, e)
            clean_phone = admin_phone

    user_repo = UserRepository(db)

    # 1. Search for existing account using normalized email or phone
    existing_user: Optional[User] = None

    if admin_email:
        existing_user = await user_repo.get_by_email(admin_email)

    if not existing_user and clean_phone:
        existing_user = await user_repo.get_by_phone(clean_phone)

    # 2. Check if any super admin account already exists with matching identifier
    if not existing_user:
        conditions = []
        if admin_email:
            conditions.append(func.lower(User.email) == admin_email)
        if clean_phone:
            phone_cond = user_repo._build_phone_filter_conditions(clean_phone)
            if phone_cond is not None:
                conditions.append(phone_cond)

        if conditions:
            stmt = select(User).where(or_(*conditions)).limit(1)
            res = await db.execute(stmt)
            existing_user = res.scalars().first()

    # If account exists, do NOT overwrite credentials or reset password
    if existing_user:
        logger.info(
            "Super Admin account already exists (id=%s, email=%s, phone=%s, role=%s). "
            "Preserving existing credentials without modification.",
            existing_user.id,
            existing_user.email,
            existing_user.phone,
            existing_user.role,
        )
        # Ensure super_admin role and phone if missing
        updated = False
        if existing_user.role != "super_admin":
            existing_user.role = "super_admin"
            updated = True
        if clean_phone and not existing_user.phone:
            existing_user.phone = clean_phone
            existing_user.is_phone_verified = True
            updated = True
        if getattr(settings, "SUPERADMIN_FORCE_RESET_PASSWORD", False) and admin_password:
            existing_user.hashed_password = hash_password(admin_password)
            logger.info("SUPERADMIN_FORCE_RESET_PASSWORD active: Password updated for Super Admin.")
            updated = True
        if updated:
            await db.commit()
            await db.refresh(existing_user)
        return existing_user

    # 3. Create initial Super Admin account
    logger.info("Provisioning initial Super Admin account (email=%s, phone=%s)...", admin_email, clean_phone)
    new_user = User(
        full_name="Enterprise Chief",
        email=admin_email,
        phone=clean_phone,
        hashed_password=hash_password(admin_password),
        role="super_admin",
        is_active=True,
        is_email_verified=True,
        is_phone_verified=True if clean_phone else False,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "Super Admin account seeded successfully (id=%s, email=%s, role=%s).",
        new_user.id,
        new_user.email,
        new_user.role,
    )
    return new_user
