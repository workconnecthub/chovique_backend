import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.platform_settings_repository import PlatformSettingsRepository

from app.schemas.auth import RegisterRequest, LoginRequest

from app.services.mail_service import MailService
from app.services.otp_service import OTPService
from app.services.google_service import GoogleService

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
        self.google_service = GoogleService()


    # ======================================================
    # REGISTER
    # ======================================================

    async def register(
        self,
        request: RegisterRequest
    ):

        logger.info("Registration attempt for email=%s", request.email)

        ps_repo = PlatformSettingsRepository(self.db)
        ps = await ps_repo.get()
        if not ps.customer_registration_enabled:
            raise ValueError("Customer registration is currently disabled by system configuration.")

        # Check password confirmation

        if request.password != request.confirm_password:
            raise ValueError(
                "Passwords do not match."
            )


        # Check existing user

        existing_user = await self.user_repo.get_by_email(
            request.email
        )

        if existing_user:
            raise ValueError(
                "Email already registered."
            )


        # Generate OTP

        otp = self.otp_service.generate_otp()


        # Save OTP (also resets attempts)

        await self.otp_service.save_otp(
            email=request.email,
            otp=otp,
            purpose="register",
        )


        # Send OTP mail

        await self.mail_service.send_registration_otp(
            email=request.email,
            otp=otp,
            name=request.full_name,
        )

        logger.info("Registration OTP sent to %s", request.email)

        return {
            "message": "OTP sent successfully.",
            "email": request.email,
            "expires_in": settings.OTP_EXPIRE_SECONDS,
        }



    # ======================================================
    # VERIFY REGISTRATION OTP
    # ======================================================

    async def verify_registration_otp(
        self,
        email: str,
        otp: str,
        full_name: str,
        password: str,
    ):

        logger.info("Verifying registration OTP for email=%s", email)

        # Verify OTP — raises typed exceptions on failure
        await self.otp_service.verify_otp(
            email=email,
            otp=otp,
            purpose="register",
        )


        # Check user again

        existing_user = await self.user_repo.get_by_email(
            email
        )

        if existing_user:
            raise ValueError(
                "Email already registered."
            )


        # Hash password

        hashed_password = hash_password(
            password
        )


        # Create user

        user = await self.user_repo.create(
            full_name=full_name,
            email=email,
            hashed_password=hashed_password,
            role="customer",
            is_email_verified=True,
            is_active=True,
        )

        # Grant Welcome Coins (200 coins immediately available in customer wallet)
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
                commit=True
            )
            await wallet_service.compute_user_coin_summary(str(user.id))


        # Generate tokens

        access_token = create_access_token(
            str(user.id)
        )


        refresh_token, jti = create_refresh_token(
            str(user.id)
        )


        # Save refresh token

        expires_at = (
            datetime.now(timezone.utc)
            +
            timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        )


        await self.refresh_repo.create(
            user_id=user.id,
            jti=jti,
            hashed_token=hash_password(
                refresh_token
            ),
            expires_at=expires_at,
        )

        logger.info("User registered successfully: id=%s email=%s", user.id, email)

        try:
            from app.repositories.notification_repository import NotificationRepository
            await NotificationRepository(self.db).create(
                user_id=user.id,
                type="welcome",
                title="Welcome to Chovique Chocolatier ✨",
                message=f"Welcome {user.full_name or 'Friend'}! Thank you for creating an account with us. Enjoy 100 bonus Welcome Coins!",
                text=f"Welcome {user.full_name or 'Friend'}! Thank you for creating an account with us.",
                related_entity_type="user",
                related_entity_id=user.id,
            )
        except Exception as notif_err:
            logger.warning("Failed to create welcome notification: %s", notif_err)

        try:
            import asyncio
            from app.integrations.resend import resend_email
            asyncio.create_task(
                resend_email.send_welcome(email=user.email, name=user.full_name or "Chocolate Lover")
            )
        except Exception as email_err:
            logger.warning("Failed to dispatch welcome email: %s", email_err)

        return {

            "message": "Registration successful.",

            "user": user,

            "access_token": access_token,

            "refresh_token": refresh_token,
        }

    # ======================================================
    # LOGIN
    # ======================================================

    async def login(
        self,
        request: LoginRequest
    ):

        logger.info("Login attempt for email=%s", request.email)

        ps_repo = PlatformSettingsRepository(self.db)
        ps = await ps_repo.get()

        # Check lockout
        lockout_key = f"login_lockout:{request.email.lower()}"
        attempts_key = f"login_attempts:{request.email.lower()}"

        try:
            from app.db.redis import redis_client
            is_locked = await redis_client.get(lockout_key)
            if is_locked:
                ttl = await redis_client.ttl(lockout_key)
                mins = max(1, (ttl + 59) // 60)
                raise ValueError(f"Account is temporarily locked due to too many failed login attempts. Please try again in {mins} minutes.")
        except ValueError:
            raise
        except Exception:
            pass

        # Check if login is for the configured Super Admin
        is_superadmin_attempt = bool(
            settings.SUPERADMIN_EMAIL
            and request.email.strip().lower() == settings.SUPERADMIN_EMAIL.strip().lower()
        )

        if is_superadmin_attempt:
            # Validate Super Admin password securely against environment configuration
            if not (settings.SUPERADMIN_PASSWORD and secrets.compare_digest(request.password, settings.SUPERADMIN_PASSWORD)):
                try:
                    from app.db.redis import redis_client
                    attempts = await redis_client.incr(attempts_key)
                    await redis_client.expire(attempts_key, 3600)
                    if attempts >= ps.max_login_attempts:
                        lockout_secs = ps.account_lockout_duration * 60
                        await redis_client.setex(lockout_key, lockout_secs, "locked")
                        await redis_client.delete(attempts_key)

                        try:
                            from app.integrations.resend import resend_email
                            from app.core.config import settings as _settings
                            await resend_email.send_superadmin_security_alert(
                                super_admin_email=_settings.SUPERADMIN_EMAIL,
                                super_admin_name="Super Admin",
                                admin_email=request.email,
                                security_event=f"Account locked after {ps.max_login_attempts} failed login attempts.",
                                detected_at=datetime.now().strftime("%d %b %Y, %I:%M %p"),
                            )
                        except Exception:
                            pass

                        raise ValueError(f"Too many failed login attempts. Account locked for {ps.account_lockout_duration} minutes.")
                except ValueError:
                    raise
                except Exception:
                    pass

                raise ValueError("Invalid email or password.")

            # Super Admin credentials valid: ensure user record exists in database for JWT / roles / foreign keys
            user = await self.user_repo.get_by_email(request.email)
            if not user:
                user = await self.user_repo.create(
                    email=settings.SUPERADMIN_EMAIL,
                    hashed_password=hash_password(settings.SUPERADMIN_PASSWORD),
                    full_name="Enterprise Chief",
                    role="superadmin",
                    is_email_verified=True,
                    is_active=True,
                )
                await self.db.commit()
            else:
                if not user.is_active:
                    raise ValueError(
                        "Your account is deactivated by the administration due to some issues. Leave a request to support.chovique.com to activate your account."
                    )
                if user.role != "superadmin":
                    user.role = "superadmin"
                    await self.db.commit()
        else:
            # Find user from database
            user = await self.user_repo.get_by_email(
                request.email
            )

            is_valid_password = False
            if user and user.hashed_password:
                is_valid_password = verify_password(
                    request.password,
                    user.hashed_password,
                )

            if not user or not is_valid_password:
                try:
                    from app.db.redis import redis_client
                    attempts = await redis_client.incr(attempts_key)
                    await redis_client.expire(attempts_key, 3600)
                    if attempts >= ps.max_login_attempts:
                        lockout_secs = ps.account_lockout_duration * 60
                        await redis_client.setex(lockout_key, lockout_secs, "locked")
                        await redis_client.delete(attempts_key)

                        try:
                            from app.integrations.resend import resend_email
                            from app.core.config import settings as _settings
                            await resend_email.send_superadmin_security_alert(
                                super_admin_email=_settings.SUPERADMIN_EMAIL,
                                super_admin_name="Super Admin",
                                admin_email=request.email,
                                security_event=f"Account locked after {ps.max_login_attempts} failed login attempts.",
                                detected_at=datetime.now().strftime("%d %b %Y, %I:%M %p"),
                            )
                        except Exception:
                            pass

                        raise ValueError(f"Too many failed login attempts. Account locked for {ps.account_lockout_duration} minutes.")
                except ValueError:
                    raise
                except Exception:
                    pass

                raise ValueError(
                    "Invalid email or password."
                )

            # Check active account after verifying credentials
            if not user.is_active:
                raise ValueError(
                    "Your account is deactivated by the administration due to some issues. Leave a request to support.chovique.com to activate your account."
                )

        # Success: clear lockout counters
        try:
            from app.db.redis import redis_client
            await redis_client.delete(attempts_key)
            await redis_client.delete(lockout_key)
        except Exception:
            pass

        # Create tokens (apply admin_session_timeout if user is admin/superadmin)
        if user.role in ("admin", "superadmin") and ps.admin_session_timeout > 0:
            access_token = create_access_token(
                str(user.id),
                expires_delta=timedelta(minutes=ps.admin_session_timeout),
            )
        else:
            access_token = create_access_token(
                str(user.id)
            )


        refresh_token, jti = create_refresh_token(
            str(user.id)
        )


        # Save refresh token

        expires_at = (
            datetime.now(timezone.utc)
            +
            timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        )


        await self.refresh_repo.create(

            user_id=user.id,

            jti=jti,

            hashed_token=hash_password(
                refresh_token
            ),

            expires_at=expires_at,
        )


        # Update last login

        await self.user_repo.update_last_login(
            user.id,
            datetime.now(timezone.utc),
        )

        try:
            await self.db.refresh(user)
        except Exception:
            pass

        logger.info("Login successful for user_id=%s", user.id)

        return {

            "message": "Login successful.",

            "user": user,

            "access_token": access_token,

            "refresh_token": refresh_token,
        }



    # ======================================================
    # GOOGLE LOGIN
    # ======================================================

    async def google_login(
        self,
        id_token: str
    ):

        logger.info("Google login attempt")

        # Verify Google token — raises ValueError on failure

        google_user = await self.google_service.verify_google_token(
            id_token
        )

        if not google_user:
            raise ValueError("Invalid Google token")

        # Include ownership verification: The email must be verified on Google
        if not google_user.get("email_verified"):
            raise ValueError("Google account email must be verified.")

        # 1. Check if user exists by google_id first
        user = await self.user_repo.get_by_google_id(
            google_user["google_id"]
        )

        # Ensure Google DP is saved into the Railway S3/Tigris bucket
        raw_avatar = google_user.get("avatar_url")
        if raw_avatar and ("googleusercontent.com" in raw_avatar or raw_avatar.startswith("http")):
            from app.services.storage_service import storage_service
            try:
                bucket_avatar_url = await storage_service.upload_from_url(
                    raw_avatar, folder="chocolate-world/avatars"
                )
                if bucket_avatar_url and "googleusercontent.com" not in bucket_avatar_url:
                    google_user["avatar_url"] = bucket_avatar_url
            except Exception as e:
                logger.warning("Failed to store Google avatar in Railway bucket: %s", e)

        # 2. If not found by google_id, check by email
        if not user:
            user = await self.user_repo.get_by_email(
                google_user["email"]
            )
            if user:
                # Link existing email account with Google ID
                await self.user_repo.update_google_data(
                    user.id,
                    google_id=google_user["google_id"],
                    avatar_url=google_user["avatar_url"],
                )
                user.google_id = google_user["google_id"]

        else:
            # Existing Google user - ensure latest Google profile DP is synced in Railway bucket
            if google_user.get("avatar_url") and (not user.avatar_url or "googleusercontent.com" in user.avatar_url):
                user.avatar_url = google_user["avatar_url"]
                await self.user_repo.update_google_data(
                    user.id,
                    google_id=google_user["google_id"],
                    avatar_url=google_user["avatar_url"],
                )

        # 3. First time Google user (neither google_id nor email exists)
        is_new_user = False
        if not user:
            is_new_user = True
            user = await self.user_repo.create(
                full_name=google_user["full_name"],
                email=google_user["email"],
                hashed_password=None,
                google_id=google_user["google_id"],
                avatar_url=google_user.get("avatar_url"),
                role="customer",
                is_email_verified=True,
                is_active=True,
            )

        # Grant 200 Welcome Coins immediately upon Google new registration
        if is_new_user:
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



        # Generate tokens


        access_token = create_access_token(
            str(user.id)
        )


        refresh_token, jti = create_refresh_token(
            str(user.id)
        )


        expires_at = (
            datetime.now(timezone.utc)
            +
            timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        )


        await self.refresh_repo.create(

            user_id=user.id,

            jti=jti,

            hashed_token=hash_password(
                refresh_token
            ),

            expires_at=expires_at,
        )


        await self.user_repo.update_last_login(
            user.id,
            datetime.now(timezone.utc),
        )

        try:
            await self.db.refresh(user)
        except Exception:
            pass

        logger.info("Google login successful for user_id=%s", user.id)

        return {

            "message": "Login successful.",

            "user": user,

            "access_token": access_token,

            "refresh_token": refresh_token,
        }




    # ======================================================
    # SET PASSWORD (GOOGLE USERS)
    # ======================================================

    async def set_password(

        self,

        user_id: str,

        password: str,

        confirm_password: str,

    ):


        user = await self.user_repo.get_by_id(
            user_id
        )


        if not user:
            raise ValueError(
                "User not found."
            )


        if password != confirm_password:

            raise ValueError(
                "Passwords do not match."
            )


        if user.hashed_password:

            raise ValueError(
                "Password already set."
            )


        hashed_password = hash_password(
            password
        )


        await self.user_repo.update_password(

            user.id,

            hashed_password

        )


        access_token = create_access_token(
            str(user.id)
        )


        refresh_token, jti = create_refresh_token(
            str(user.id)
        )


        expires_at = (
            datetime.now(timezone.utc)
            +
            timedelta(
                days=settings.REFRESH_TOKEN_EXPIRE_DAYS
            )
        )


        await self.refresh_repo.create(

            user_id=user.id,

            jti=jti,

            hashed_token=hash_password(
                refresh_token
            ),

            expires_at=expires_at,
        )


        return {

            "message": "Password set successfully.",

            "user": user,

            "access_token": access_token,

            "refresh_token": refresh_token,
        }




    # ======================================================
    # RESEND REGISTRATION OTP
    # ======================================================

    async def resend_otp(
        self,
        email: str,
    ):

        existing_user = await self.user_repo.get_by_email(email)

        if existing_user and existing_user.is_email_verified:
            return {
                "message": "OTP resent successfully.",
                "email": email,
                "expires_in": settings.OTP_EXPIRE_SECONDS,
            }

        await self.otp_service.check_resend_limit(email, purpose="register")

        otp = self.otp_service.generate_otp()

        # save_otp automatically resets attempts
        await self.otp_service.save_otp(
            email=email,
            otp=otp,
            purpose="register",
        )

        await self.otp_service.record_resend(email, purpose="register")

        resend_name = existing_user.full_name if existing_user else ""

        await self.mail_service.send_resend_registration_otp(
            email=email,
            otp=otp,
            name=resend_name,
        )

        logger.info("Registration OTP resent to %s", email)

        return {
            "message": "OTP resent successfully.",
            "email": email,
            "expires_in": settings.OTP_EXPIRE_SECONDS,
        }

    # ======================================================
    # FORGOT PASSWORD
    # ======================================================

    async def forgot_password(
        self,
        email: str
    ):

        logger.info("Forgot password request for email=%s", email)

        user = await self.user_repo.get_by_email(
            email
        )

        # Don't expose email existence
        if not user:
            return {
                "message":
                "If email exists, OTP has been sent.",
            }

        otp = self.otp_service.generate_otp()

        # save_otp automatically resets attempts
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

        return {"message": "If email exists, OTP has been sent."}

    # ======================================================
    # RESEND FORGOT PASSWORD OTP
    # ======================================================

    async def resend_forgot_password_otp(
        self,
        email: str,
    ):
        """Resend OTP for forgot password flow."""

        logger.info("Resend forgot password OTP request for email=%s", email)

        await self.otp_service.check_resend_limit(email, purpose="forgot")

        user = await self.user_repo.get_by_email(email)

        # Don't expose email existence
        if not user:
            return {
                "message": "If email exists, OTP has been sent.",
            }

        otp = self.otp_service.generate_otp()

        # save_otp automatically resets attempts
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

        return {"message": "If email exists, OTP has been sent."}


    # ======================================================
    # RESET PASSWORD
    # ======================================================

    async def reset_password(

        self,

        email: str,

        otp: str,

        password: str,

        confirm_password: str,

    ):

        logger.info("Reset password attempt for email=%s", email)

        if password != confirm_password:

            raise ValueError(
                "Passwords do not match."
            )


        # Raises typed exceptions on failure
        await self.otp_service.verify_otp(

            email=email,

            otp=otp,

            purpose="forgot",

        )



        user = await self.user_repo.get_by_email(
            email
        )


        if not user:

            raise ValueError(
                "User not found."
            )



        await self.user_repo.update_password(

            user.id,

            hash_password(password)

        )


        # Invalidate old sessions

        await self.refresh_repo.revoke_all_user_tokens(
            user.id
        )

        logger.info("Password reset successful for user_id=%s", user.id)

        return {

            "message":
            "Password reset successful."

        }

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