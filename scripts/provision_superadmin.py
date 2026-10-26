"""
Provision Super Admin Account
=============================
Secure provisioning utility for the initial Super Admin account.
Usage:
    python scripts/provision_superadmin.py --phone 9876543210 --email superadmin@chovique.com --password "YourStrongPassword123!"
Or:
    python scripts/provision_superadmin.py  (reads from SUPERADMIN_PHONE, SUPERADMIN_EMAIL, SUPERADMIN_PASSWORD in .env)
"""

import argparse
import asyncio
import getpass
import sys
from sqlalchemy import select, or_, func

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.integrations.msg91 import parse_and_normalize_phone
from app.models.user import User


async def provision_superadmin(
    phone: str,
    email: str,
    password: str,
    name: str = "Enterprise Chief",
    reset_password: bool = False,
) -> None:
    clean_email = email.strip().lower()
    clean_phone, _, _ = parse_and_normalize_phone(phone, default_country_code="+91")

    if not clean_email:
        raise ValueError("Super Admin email is required.")

    async with AsyncSessionLocal() as db:
        # Check by email or phone or super admin role
        stmt = select(User).where(
            or_(
                func.lower(User.email) == clean_email,
                User.phone == clean_phone,
                User.phone == clean_phone.lstrip("+"),
            )
        ).limit(1)
        res = await db.execute(stmt)
        user = res.scalars().first()

        if user:
            print(f"Super Admin account already exists (ID: {user.id}, Email: {user.email}, Phone: {user.phone}).")
            if reset_password:
                if len(password) < 8:
                    raise ValueError("Super Admin password must be at least 8 characters.")
                user.hashed_password = hash_password(password)
                print("Password reset for existing Super Admin account.")
            user.phone = clean_phone
            user.role = "super_admin"
            user.is_active = True
            user.is_phone_verified = True
            user.is_email_verified = True
            await db.commit()
            print(f"[SUCCESS] Super Admin account validated:")
            print(f"   Name:     {user.full_name}")
            print(f"   Role:     {user.role}")
            print(f"   Mobile:   {user.phone}")
            print(f"   Email:    {user.email}")
        else:
            if len(password) < 8:
                raise ValueError("Super Admin password must be at least 8 characters.")
            hashed_pwd = hash_password(password)
            print("Creating initial Super Admin account...")
            new_user = User(
                full_name=name,
                email=clean_email,
                phone=clean_phone,
                hashed_password=hashed_pwd,
                role="super_admin",
                is_active=True,
                is_phone_verified=True,
                is_email_verified=True,
            )
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
            print(f"[SUCCESS] Initial Super Admin created successfully:")
            print(f"   ID:       {new_user.id}")
            print(f"   Name:     {new_user.full_name}")
            print(f"   Role:     {new_user.role}")
            print(f"   Mobile:   {new_user.phone}")
            print(f"   Email:    {new_user.email}")


def main():
    parser = argparse.ArgumentParser(description="Provision Chovique Super Admin Account")
    parser.add_argument("--phone", help="Super Admin 10-digit mobile number", default=settings.SUPERADMIN_PHONE)
    parser.add_argument("--email", help="Super Admin email address", default=settings.SUPERADMIN_EMAIL)
    parser.add_argument("--password", help="Super Admin password (or prompt if omitted)", default=settings.SUPERADMIN_PASSWORD)
    parser.add_argument("--name", help="Full name", default="Enterprise Chief")
    parser.add_argument("--reset-password", action="store_true", help="Explicitly reset password if user exists")

    args = parser.parse_args()

    phone = args.phone
    if not phone:
        if sys.stdin.isatty():
            phone = input("Enter Super Admin Mobile Number (10 digits): ").strip()
        else:
            phone = "919876543210"

    email = args.email or "superadmin@chovique.com"

    password = args.password
    if not password and not args.reset_password:
        password = settings.SUPERADMIN_PASSWORD
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("Enter Super Admin Password: ")
        else:
            raise ValueError("Super Admin password is required via --password or .env")

    asyncio.run(provision_superadmin(
        phone=phone,
        email=email,
        password=password,
        name=args.name,
        reset_password=args.reset_password,
    ))


if __name__ == "__main__":
    main()
