from typing import Optional, Dict, Any, Tuple
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.platform_settings_repository import PlatformSettingsRepository

from app.services.mail_service import MailService
from app.services.otp_service import OTPService

from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)

from app.core.config import settings
from app.core.exceptions import (
    InvalidOTPError,
    MaxAttemptsExceededError,
    OTPExpiredError,
)

logger = logging.getLogger(__name__)


class AuthService:

    def __init__(self, db: AsyncSession):

        self.db = db

        self.user_repo = UserRepository(db)
        self.refresh_repo = RefreshTokenRepository(db)

        self.mail_service = MailService()
        self.otp_service = OTPService()



    # ======================================================
    # FORGOT PASSWORD
    # ======================================================

    async def forgot_password(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ):
        identifier = phone or email
        if not identifier:
            raise ValueError("Email or mobile number is required.")

        if phone:
            from app.integrations.msg91 import normalize_phone
            clean_phone = normalize_phone(phone)
            user = await self.user_repo.get_by_phone(clean_phone)
            if user and user.role in ("admin", "superadmin", "super_admin", "delivery_boy", "delivery_person"):
                await self.otp_service.send_customer_otp(self.db, clean_phone, is_resend=False)
            return {
                "message": "If an active staff account exists for this mobile number, an OTP has been sent.",
                "expires_in": settings.OTP_EXPIRE_SECONDS,
            }

        # Email fallback
        user = await self.user_repo.get_by_email(email)
        if not user:
            return {
                "message": "If email exists, OTP has been sent.",
                "expires_in": settings.OTP_EXPIRE_SECONDS,
            }

        otp = self.otp_service.generate_otp()
        await self.otp_service.save_otp(
            email=email,
            otp=otp,
            purpose="forgot",
        )
        await self.mail_service.send_forgot_password_otp(
            email=email,
            otp=otp,
            name=user.full_name,
        )
        logger.info("Forgot password OTP sent to %s", email)
        return {
            "message": "If email exists, OTP has been sent.",
            "expires_in": settings.OTP_EXPIRE_SECONDS,
        }

    # ======================================================
    # RESEND FORGOT PASSWORD OTP
    # ======================================================

    async def resend_forgot_password_otp(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
    ):
        if phone:
            return await self.forgot_password(phone=phone)

        if not email:
            raise ValueError("Email or mobile number is required.")

        await self.otp_service.check_resend_limit(email, purpose="forgot")
        user = await self.user_repo.get_by_email(email)
        if not user:
            return {
                "message": "If email exists, OTP has been sent.",
                "expires_in": settings.OTP_EXPIRE_SECONDS,
            }

        otp = self.otp_service.generate_otp()
        await self.otp_service.save_otp(
            email=email,
            otp=otp,
            purpose="forgot",
        )
        await self.otp_service.record_resend(email, purpose="forgot")
        await self.mail_service.send_forgot_password_otp(
            email=email,
            otp=otp,
            name=user.full_name,
            is_resend=True,
        )
        logger.info("Forgot password OTP resent to %s", email)
        return {
            "message": "If email exists, OTP has been sent.",
            "expires_in": settings.OTP_EXPIRE_SECONDS,
        }

    # ======================================================
    # RESET PASSWORD
    # ======================================================

    async def reset_password(
        self,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        otp: str = "",
        password: str = "",
        confirm_password: str = "",
    ):
        if password != confirm_password:
            raise ValueError("Passwords do not match.")

        if phone:
            from app.integrations.msg91 import normalize_phone
            clean_phone = normalize_phone(phone)
            await self.otp_service.verify_customer_otp(self.db, clean_phone, otp)
            user = await self.user_repo.get_by_phone(clean_phone)
            if not user or user.role not in ("admin", "superadmin", "super_admin", "delivery_boy", "delivery_person"):
                raise ValueError("Staff account not found.")

            await self.user_repo.update_password(user.id, hash_password(password))
            await self.refresh_repo.revoke_all_user_tokens(user.id)
            logger.info("Password reset successful for staff user_id=%s", user.id)
            return {"message": "Password reset successful."}

        if email:
            await self.otp_service.verify_otp(
                email=email,
                otp=otp,
                purpose="forgot",
            )
            user = await self.user_repo.get_by_email(email)
            if not user:
                raise ValueError("User not found.")

            await self.user_repo.update_password(user.id, hash_password(password))
            await self.refresh_repo.revoke_all_user_tokens(user.id)
            logger.info("Password reset successful for user_id=%s", user.id)
            return {"message": "Password reset successful."}

        raise ValueError("Phone or email is required.")

    # ======================================================
    # CHANGE PASSWORD
    # ======================================================

    async def change_password(

        self,

        user_id: str,

        current_password: str,

        new_password: str,

        confirm_password: str,

    ):


        user = await self.user_repo.get_by_id(
            user_id
        )


        if not user:

            raise ValueError(
                "User not found."
            )


        # Google user without password

        if not user.hashed_password:

            raise ValueError(
                "Please set password first."
            )


        # Verify old password

        if not verify_password(

            current_password,

            user.hashed_password,

        ):

            raise ValueError(
                "Current password is incorrect."
            )


        if new_password != confirm_password:

            raise ValueError(
                "Passwords do not match."
            )


        # Update password

        await self.user_repo.update_password(

            user.id,

            hash_password(
                new_password
            )

        )


        # Logout all devices

        await self.refresh_repo.revoke_all_user_tokens(
            user.id
        )


        return {

            "message":
            "Password changed successfully."

        }

    # ======================================================
    # UPDATE PASSWORD WITH OTP
    # ======================================================

    async def send_update_password_otp(self, user_id: str, email: str):
        user = await self.user_repo.get_by_id(user_id)
        if not user or user.email != email:
            raise ValueError("Email does not match the authenticated user.")

        otp = self.otp_service.generate_otp()
        await self.otp_service.save_otp(
            email=email,
            otp=otp,
            purpose="update_password",
        )
        await self.mail_service.send_update_password_otp(
            email=email,
            otp=otp,
            name=user.full_name,
        )
        return {"message": "OTP sent successfully."}

    async def verify_update_password_otp(self, user_id: str, email: str, otp: str):
        user = await self.user_repo.get_by_id(user_id)
        if not user or user.email != email:
            raise ValueError("Email does not match the authenticated user.")

        await self.otp_service.verify_otp(
            email=email,
            otp=otp,
            purpose="update_password",
        )
        await self.otp_service.mark_otp_verified(email, "update_password")
        return {"message": "OTP verified successfully."}

    async def update_password_with_otp(
        self, user_id: str, email: str, new_password: str, confirm_password: str
    ):
        user = await self.user_repo.get_by_id(user_id)
        if not user or user.email != email:
            raise ValueError("Email does not match the authenticated user.")

        if new_password != confirm_password:
            raise ValueError("Passwords do not match.")

        if not await self.otp_service.is_otp_verified(email, "update_password"):
            raise ValueError("OTP verification is required before updating password.")

        await self.user_repo.update_password(
            user.id,
            hash_password(new_password)
        )
        await self.refresh_repo.revoke_all_user_tokens(user.id)

        return {"message": "Password updated successfully."}

    # ======================================================
    # REFRESH TOKEN
    # ======================================================

    async def refresh_token(

        self,

        refresh_token: str,

    ):


        # Decode token

        payload = decode_token(
            refresh_token
        )


        if not payload:

            raise ValueError(
                "Invalid refresh token."
            )


        if payload.get("type") != "refresh":

            raise ValueError(
                "Invalid token type."
            )


        user_id = payload.get(
            "sub"
        )


        jti = payload.get(
            "jti"
        )


        if not user_id or not jti:

            raise ValueError(
                "Invalid token payload."
            )



        # Find token in DB

        db_token = await self.refresh_repo.get_by_jti(
            jti
        )


        if not db_token:

            raise ValueError(
                "Refresh token not found."
            )


        if db_token.revoked_at:

            raise ValueError(
                "Refresh token revoked."
            )


        if db_token.expires_at < datetime.now(
            timezone.utc
        ):

            raise ValueError(
                "Refresh token expired."
            )



        # Compare hashed token

        if not verify_password(

            refresh_token,

            db_token.hashed_token,

        ):

            raise ValueError(
                "Invalid refresh token."
            )



        # Create new tokens

        access_token = create_access_token(
            user_id
        )


        new_refresh_token, new_jti = create_refresh_token(
            user_id
        )


        expires_at = (
            datetime.now(timezone.utc)
            +
            timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        )



        # Revoke old refresh token

        await self.refresh_repo.revoke(
            jti
        )



        # Save new refresh token

        await self.refresh_repo.create(

            user_id=user_id,

            jti=new_jti,

            hashed_token=hash_password(
                new_refresh_token
            ),

            expires_at=expires_at,

        )



        return {

            "access_token":
            access_token,


            "refresh_token":
            new_refresh_token,

        }




    # ======================================================
    # LOGOUT
    # ======================================================

    async def logout(
        self,
        refresh_token: str | None = None,
        access_token: str | None = None,
    ):


        if refresh_token:
            payload = decode_token(
                refresh_token
            )
            if payload:
                jti = payload.get(
                    "jti"
                )
                if jti:
                    await self.refresh_repo.revoke(
                        jti
                    )
                    
        if access_token:
            payload = decode_token(access_token)
            if payload:
                exp = payload.get("exp")
                if exp:
                    now = int(datetime.now(timezone.utc).timestamp())
                    ttl = exp - now
                    if ttl > 0:
                        from app.db.redis import redis_client
                        await redis_client.setex(f"blocklist:{access_token}", ttl, "1")



        return {
            "message":
            "Logout successful."
        }

    # ======================================================
    # CUSTOMER MOBILE OTP AUTHENTICATION
    # ======================================================

    async def customer_send_otp(self, phone: str) -> dict:
        """Send OTP to customer mobile number via MSG91 with cooldown and limit enforcement."""
        from fastapi import HTTPException, status
        from app.integrations.msg91 import normalize_phone
        clean_phone = normalize_phone(phone)

        # Guardrail: Check if staff account exists
        staff_user = await self.user_repo.get_staff_by_phone(clean_phone)
        if staff_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )

        all_accounts = await self.user_repo.get_all_by_phone(clean_phone)
        if any(u.role != "customer" for u in all_accounts):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )

        message, expires_in, cooldown, remaining = await self.otp_service.send_customer_otp(
            db=self.db,
            phone=clean_phone,
            is_resend=False,
        )
        return {
            "message": message,
            "phone": clean_phone,
            "expires_in": expires_in,
            "cooldown_seconds": cooldown,
            "remaining_daily_requests": remaining,
        }

    async def customer_resend_otp(self, phone: str) -> dict:
        """Resend OTP to customer mobile number via MSG91 with cooldown and limit enforcement."""
        from fastapi import HTTPException, status
        from app.integrations.msg91 import normalize_phone
        clean_phone = normalize_phone(phone)

        # Guardrail: Check if staff account exists
        staff_user = await self.user_repo.get_staff_by_phone(clean_phone)
        if staff_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )

        all_accounts = await self.user_repo.get_all_by_phone(clean_phone)
        if any(u.role != "customer" for u in all_accounts):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )

        message, expires_in, cooldown, remaining = await self.otp_service.send_customer_otp(
            db=self.db,
            phone=clean_phone,
            is_resend=True,
        )
        return {
            "message": message,
            "phone": clean_phone,
            "expires_in": expires_in,
            "cooldown_seconds": cooldown,
            "remaining_daily_requests": remaining,
        }

    async def identify_mobile(self, mobile_number: str, country_code: Optional[str] = "+91") -> dict:
        """
        Validate mobile number and determine the next authentication step.
        - Staff (superadmin, admin, delivery_boy):
            If inactive -> 403.
            If active -> returns next_step='password'.
        - Customer (or new customer):
            Enforces 5-OTP daily limit and 60s cooldown.
            Sends OTP via MSG91.
            Returns next_step='otp'.
        """
        from fastapi import HTTPException, status
        from app.integrations.msg91 import parse_and_normalize_phone
        clean_phone, national_phone, cc_str = parse_and_normalize_phone(mobile_number, default_country_code=country_code)

        # 1. Authoritative check: Search PostgreSQL for existing staff account
        staff_user = await self.user_repo.get_staff_by_phone(clean_phone)

        # Superadmin fallback to configured settings phone
        if not staff_user and settings.SUPERADMIN_PHONE:
            from app.schemas.auth import validate_phone_number
            if clean_phone == validate_phone_number(settings.SUPERADMIN_PHONE):
                sa_user = await self.user_repo.get_by_email(settings.SUPERADMIN_EMAIL)
                if sa_user:
                    sa_user.phone = clean_phone
                    await self.db.commit()
                    await self.db.refresh(sa_user)
                    staff_user = sa_user

        if staff_user:
            if not staff_user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your staff account has been deactivated. Please contact an administrator.",
                )
            return {
                "next_step": "password",
                "message": "Password authentication required",
                "phone": clean_phone,
                "country_code": cc_str,
                "mobile_number": national_phone,
            }

        # 2. Check all matching accounts in PostgreSQL
        all_accounts = await self.user_repo.get_all_by_phone(clean_phone)
        if all_accounts:
            non_customer = [u for u in all_accounts if u.role != "customer"]
            if non_customer:
                acct = non_customer[0]
                if not acct.is_active:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Account is deactivated. Please contact an administrator.",
                    )
                return {
                    "next_step": "password",
                    "message": "Password authentication required",
                    "phone": clean_phone,
                    "country_code": cc_str,
                    "mobile_number": national_phone,
                }

        # 3. Otherwise: customer login or new customer registration
        message, expires_in, cooldown, remaining = await self.otp_service.send_customer_otp(
            db=self.db,
            phone=clean_phone,
            is_resend=False,
        )

        return {
            "next_step": "otp",
            "message": message or "OTP verification required",
            "phone": clean_phone,
            "country_code": cc_str,
            "mobile_number": national_phone,
            "expires_in": expires_in,
            "resend_cooldown": cooldown,
            "remaining_daily_requests": remaining,
        }

    async def customer_verify_otp(self, phone: str, otp: str) -> dict:
        """
        Verify submitted customer OTP, consume challenge, and either authenticate
        existing customer or atomically create new customer account without duplicates.
        """
        from app.integrations.msg91 import normalize_phone
        from app.models.user import User
        from app.models.cart import Cart
        import uuid
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy import select
        from fastapi import HTTPException, status

        clean_phone = normalize_phone(phone)

        # 0. Guardrail: Never allow staff accounts into customer verification
        staff_user = await self.user_repo.get_staff_by_phone(clean_phone)
        if staff_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )
        all_accounts = await self.user_repo.get_all_by_phone(clean_phone)
        if any(u.role != "customer" for u in all_accounts):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal.",
            )

        # 1. Verify OTP with attempts tracking and expiry
        await self.otp_service.verify_customer_otp(
            db=self.db,
            phone=clean_phone,
            otp=otp,
        )

        customer_accounts = [u for u in all_accounts if u.role == "customer"]
        if customer_accounts:
            user = customer_accounts[0]
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is deactivated. Please contact support.",
                )
        else:
            # 3. First-time customer: create account atomically
            is_new = True
            new_id = str(uuid.uuid4())
            new_user = User(
                id=new_id,
                full_name="Customer",
                phone=clean_phone,
                role="customer",
                is_phone_verified=True,
                is_email_verified=False,
                is_active=True,
            )
            self.db.add(new_user)
            try:
                await self.db.commit()
                await self.db.refresh(new_user)
                user = new_user
            except IntegrityError:
                # Handled race condition: concurrent verification created user in parallel
                await self.db.rollback()
                user = await self.user_repo.get_by_phone(clean_phone)
                if not user or user.role != "customer":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN if user else status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="This mobile number is registered as a staff account. Please sign in via the Staff Portal." if user else "Error creating customer account. Please try again.",
                    )
                is_new = False

            # Ensure cart exists for new customer
            if is_new:
                try:
                    cart_res = await self.db.execute(select(Cart).where(Cart.user_id == user.id))
                    if not cart_res.scalar_one_or_none():
                        self.db.add(Cart(user_id=user.id))
                        await self.db.commit()
                except Exception as e:
                    logger.warning("Auto cart creation note: %s", e)

                # Welcome coins grant
                try:
                    from app.services.wallet_service import WalletService
                    wallet_service = WalletService(self.db)
                    reward_settings = await wallet_service.get_reward_settings()
                    welcome_amt = getattr(reward_settings, "welcome_coins", 200) or 200
                    if reward_settings.reward_system_enabled and welcome_amt > 0:
                        await wallet_service.wallet_repo.add_transaction(
                            user_id=str(user.id),
                            transaction_type="WELCOME",
                            coins=welcome_amt,
                            description="Welcome Bonus — Registration Reward",
                            commit=True,
                        )
                        await wallet_service.compute_user_coin_summary(str(user.id))
                except Exception as e:
                    logger.warning("Welcome coin bonus note: %s", e)

        # 4. Update last login timestamp
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        # 5. Issue access token and refresh token
        access_token = create_access_token(str(user.id))
        refresh_token, jti = create_refresh_token(str(user.id))
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await self.refresh_repo.create(
            user_id=user.id,
            jti=jti,
            hashed_token=hash_password(refresh_token),
            expires_at=expires_at,
        )

        logger.info("Customer logged in successfully (phone=%s, id=%s)", clean_phone, user.id)

        return {
            "message": "Login successful.",
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }

    # ======================================================
    # STAFF AUTHENTICATION
    # ======================================================

    async def staff_check_mobile(self, phone: str, role: str) -> dict:
        """
        Validate that an active staff account exists for the given mobile number and role.
        Returns minimal response. Does not issue authentication tokens.
        """
        from app.schemas.auth import validate_phone_number, normalize_staff_role
        from fastapi import HTTPException, status
        clean_phone = validate_phone_number(phone)
        normalized_role = normalize_staff_role(role)

        # Check if Superadmin matches settings phone
        is_superadmin_configured = bool(
            normalized_role == "superadmin"
            and settings.SUPERADMIN_PHONE
            and clean_phone == validate_phone_number(settings.SUPERADMIN_PHONE)
        )

        user = await self.user_repo.get_by_phone_and_role(clean_phone, normalized_role)

        if not user and is_superadmin_configured:
            # Sync superadmin user phone if account was seeded with email
            user = await self.user_repo.get_by_email(settings.SUPERADMIN_EMAIL)
            if user:
                user.phone = clean_phone
                await self.db.commit()
                await self.db.refresh(user)
            else:
                user = await self.user_repo.create(
                    email=settings.SUPERADMIN_EMAIL,
                    phone=clean_phone,
                    hashed_password=hash_password(settings.SUPERADMIN_PASSWORD),
                    full_name="Enterprise Chief",
                    role="superadmin",
                    is_email_verified=True,
                    is_phone_verified=True,
                    is_active=True,
                )
                await self.db.commit()

        roles_match = bool(
            user
            and (
                user.role == normalized_role
                or (user.role in ("delivery_boy", "delivery_person") and normalized_role in ("delivery_boy", "delivery_person"))
                or (user.role in ("superadmin", "super_admin") and normalized_role in ("superadmin", "super_admin"))
            )
        )
        if not user or not roles_match:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active staff account found for this mobile number and role.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Please contact an administrator.",
            )

        return {
            "exists": True,
            "role": role,
            "message": "Mobile number verified. Please enter your password to continue.",
        }

    async def staff_login(self, phone: str, password: str, role: Optional[str] = None) -> dict:
        """
        Independently verify staff mobile number, Argon2 password hash, role, and account status.
        If role is specified, rejects role mismatches. If role is omitted, automatically resolves
        authorized staff role from the database.
        Issues credentials only upon full verification.
        """
        from app.schemas.auth import validate_phone_number, normalize_staff_role
        from fastapi import HTTPException, status
        clean_phone = validate_phone_number(phone)
        normalized_role = normalize_staff_role(role) if (role and str(role).strip()) else None

        # Check lockout
        lockout_key = f"staff_login_lockout:{clean_phone}"
        attempts_key = f"staff_login_attempts:{clean_phone}"

        try:
            from app.db.redis import redis_client
            is_locked = await redis_client.get(lockout_key)
            if is_locked:
                ttl = await redis_client.ttl(lockout_key)
                mins = max(1, (ttl + 59) // 60)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Account temporarily locked due to too many failed attempts. Try again in {mins} minute(s).",
                )
        except HTTPException:
            raise
        except Exception:
            pass

        staff_roles = ("superadmin", "admin", "delivery_boy", "super_admin", "delivery_person")
        if normalized_role:
            user = await self.user_repo.get_by_phone_and_role(clean_phone, normalized_role)
        else:
            user = await self.user_repo.get_staff_by_phone(clean_phone)
            if not user:
                user = await self.user_repo.get_by_phone(clean_phone)
                if user and user.role not in staff_roles:
                    user = None

        # Superadmin fallback to settings
        if not user and (normalized_role in ("superadmin", "super_admin") or normalized_role is None) and settings.SUPERADMIN_PHONE:
            if clean_phone == validate_phone_number(settings.SUPERADMIN_PHONE):
                user = await self.user_repo.get_by_email(settings.SUPERADMIN_EMAIL)
                if user:
                    user.phone = clean_phone
                    await self.db.commit()
                    await self.db.refresh(user)

        roles_match = bool(
            user
            and (
                not normalized_role
                or user.role == normalized_role
                or (user.role in ("delivery_boy", "delivery_person") and normalized_role in ("delivery_boy", "delivery_person"))
                or (user.role in ("superadmin", "super_admin") and normalized_role in ("superadmin", "super_admin"))
            )
        )
        if not user or not roles_match or (user.role not in staff_roles):
            try:
                from app.db.redis import redis_client
                attempts = await redis_client.incr(attempts_key)
                await redis_client.expire(attempts_key, 3600)
                if attempts >= 5:
                    await redis_client.setex(lockout_key, 600, "locked")
                    await redis_client.delete(attempts_key)
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid mobile number, role, or password.",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Please contact an administrator.",
            )

        # Verify password using Argon2 / bcrypt
        is_valid_pwd = False
        if user.hashed_password:
            is_valid_pwd = verify_password(password, user.hashed_password)
        elif normalized_role in ("superadmin", "super_admin") and settings.SUPERADMIN_PASSWORD:
            is_valid_pwd = secrets.compare_digest(password, settings.SUPERADMIN_PASSWORD)
            if is_valid_pwd:
                user.hashed_password = hash_password(password)
                await self.db.commit()

        if not is_valid_pwd:
            try:
                from app.db.redis import redis_client
                attempts = await redis_client.incr(attempts_key)
                await redis_client.expire(attempts_key, 3600)
                if attempts >= 5:
                    await redis_client.setex(lockout_key, 600, "locked")
                    await redis_client.delete(attempts_key)
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid mobile number, role, or password.",
            )

        # Clear lockout counters on success
        try:
            from app.db.redis import redis_client
            await redis_client.delete(attempts_key)
            await redis_client.delete(lockout_key)
        except Exception:
            pass

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(user)

        access_token = create_access_token(str(user.id))
        refresh_token, jti = create_refresh_token(str(user.id))
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        await self.refresh_repo.create(
            user_id=user.id,
            jti=jti,
            hashed_token=hash_password(refresh_token),
            expires_at=expires_at,
        )

        logger.info("Staff logged in successfully (phone=%s, role=%s, id=%s)", clean_phone, user.role, user.id)

        return {
            "message": "Login successful.",
            "user": user,
            "access_token": access_token,
            "refresh_token": refresh_token,
        }