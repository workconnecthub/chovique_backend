import logging

from fastapi import (
    APIRouter,
    Depends,
    Response,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.services.auth_service import AuthService
from app.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    ResendForgotOTPRequest,
    UpdatePasswordSendOTPRequest,
    UpdatePasswordVerifyOTPRequest,
    UpdatePasswordRequest,
    AuthUserResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ForgotPasswordResponse,
    CustomerSendOTPRequest,
    CustomerSendOTPResponse,
    CustomerResendOTPRequest,
    CustomerVerifyOTPRequest,
    StaffCheckMobileRequest,
    StaffCheckMobileResponse,
    StaffLoginRequest,
    StaffForgotPasswordRequest,
    IdentifyRequest,
    IdentifyResponse,
)
from app.schemas.token import MessageResponse
from app.schemas.user import UserResponse
from app.api.deps import get_current_user_id, get_current_user, _extract_token
from app.models.user import User
from app.middleware.rate_limit_middleware import RateLimiter
from app.core.config import settings
from app.core.exceptions import (
    InvalidOTPError,
    MaxAttemptsExceededError,
    OTPExpiredError,
)
from fastapi import Cookie, Header

logger = logging.getLogger(__name__)

router = APIRouter( prefix="/auth", tags=["Authentication"])


# ======================================================
# OTP Exception Handler Helper
# ======================================================

def _handle_otp_exception(e: Exception):
    """Convert OTP exceptions to appropriate HTTP errors."""

    if isinstance(e, MaxAttemptsExceededError):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=e.message,
        )

    if isinstance(e, OTPExpiredError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )

    if isinstance(e, InvalidOTPError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=e.message,
        )


# ======================================================
# Cookie Helpers
# ======================================================

def generate_csrf_token() -> str:
    import secrets
    return secrets.token_urlsafe(32)


def set_auth_cookies(response: Response, access_token: str, refresh_token: str, csrf_token: str | None = None):
    is_prod = not settings.DEBUG
    samesite_mode = "none" if is_prod else "lax"
    secure_mode = is_prod

    # Access Token Cookie (HttpOnly)
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=secure_mode,
        samesite=samesite_mode,
        max_age=60 * settings.ACCESS_TOKEN_EXPIRE_MINUTES,
    )

    # Refresh Token Cookie (HttpOnly)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=secure_mode,
        samesite=samesite_mode,
        max_age=60 * 60 * 24 * settings.REFRESH_TOKEN_EXPIRE_DAYS,
    )

    # CSRF Token Cookie (HttpOnly=False so frontend JS can read it for Double Submit Cookie pattern)
    if not csrf_token:
        csrf_token = generate_csrf_token()

    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        secure=secure_mode,
        samesite=samesite_mode,
        max_age=60 * 60 * 24 * settings.REFRESH_TOKEN_EXPIRE_DAYS,
    )
    return csrf_token


def clear_auth_cookies(response: Response):
    """
    Consistently clear all authentication and session cookies across environments.
    Matches SameSite, Secure, and path attributes used during cookie creation.
    """
    is_prod = not settings.DEBUG
    samesite_mode = "none" if is_prod else "lax"
    secure_mode = is_prod

    response.delete_cookie(
        key="access_token",
        path="/",
        httponly=True,
        secure=secure_mode,
        samesite=samesite_mode,
    )
    response.delete_cookie(
        key="refresh_token",
        path="/",
        httponly=True,
        secure=secure_mode,
        samesite=samesite_mode,
    )
    response.delete_cookie(
        key="csrf_token",
        path="/",
        httponly=False,
        secure=secure_mode,
        samesite=samesite_mode,
    )



# ======================================================
# CSRF TOKEN
# ======================================================

@router.get("/csrf", summary="Get CSRF Token")
def get_csrf_token(response: Response):
    token = generate_csrf_token()
    is_prod = not settings.DEBUG
    response.set_cookie(
        key="csrf_token",
        value=token,
        httponly=False,
        secure=is_prod,
        samesite="none" if is_prod else "lax",
    )
    return {"csrf_token": token}


# ======================================================
# UNIFIED LOGIN IDENTIFY ENDPOINT
# ======================================================

@router.post(
    "/identify",
    response_model=IdentifyResponse,
    summary="Validate mobile number and determine next authentication step (OTP or Password)",
    dependencies=[Depends(RateLimiter(times=15, seconds=60))],
)
async def identify_mobile(
    request: IdentifyRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        mobile = request.mobile_number or request.phone
        country_code = request.country_code or "+91"
        return await service.identify_mobile(mobile, country_code=country_code)
    except (InvalidOTPError, OTPExpiredError, MaxAttemptsExceededError) as e:
        _handle_otp_exception(e)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error identifying mobile number: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to process mobile number.")


# ======================================================
# CUSTOMER OTP AUTHENTICATION
# ======================================================

@router.post(
    "/customer/send-otp",
    response_model=CustomerSendOTPResponse,
    summary="Send OTP to customer mobile number",
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
async def customer_send_otp(
    request: CustomerSendOTPRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.customer_send_otp(request.phone)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error sending customer OTP: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send OTP.")


@router.post(
    "/customer/resend-otp",
    response_model=CustomerSendOTPResponse,
    summary="Resend OTP to customer mobile number",
    dependencies=[Depends(RateLimiter(times=3, seconds=60))],
)
async def customer_resend_otp(
    request: CustomerResendOTPRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.customer_resend_otp(request.phone)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Error resending customer OTP: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to resend OTP.")


@router.post(
    "/customer/verify-otp",
    response_model=AuthUserResponse,
    summary="Verify customer OTP and login or auto-create account",
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
async def customer_verify_otp(
    request: CustomerVerifyOTPRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        result = await service.customer_verify_otp(phone=request.phone, otp=request.otp)
        set_auth_cookies(
            response,
            result["access_token"],
            result["refresh_token"],
        )
        return {
            "message": result["message"],
            "user": UserResponse.from_orm_user(result["user"]),
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
        }
    except (InvalidOTPError, OTPExpiredError, MaxAttemptsExceededError) as e:
        _handle_otp_exception(e)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ======================================================
# STAFF AUTHENTICATION
# ======================================================

@router.post(
    "/staff/check-mobile",
    response_model=StaffCheckMobileResponse,
    summary="Validate staff mobile number and role",
    dependencies=[Depends(RateLimiter(times=10, seconds=60))],
)
async def staff_check_mobile(
    request: StaffCheckMobileRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.staff_check_mobile(phone=request.phone, role=request.role)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/staff/login",
    response_model=AuthUserResponse,
    summary="Staff password login with role and mobile number verification",
    dependencies=[Depends(RateLimiter(times=5, seconds=60))],
)
async def staff_login(
    request: StaffLoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        result = await service.staff_login(
            phone=request.phone or request.mobile_number,
            password=request.password,
            role=request.role,
        )
        set_auth_cookies(
            response,
            result["access_token"],
            result["refresh_token"],
        )
        return {
            "message": result["message"],
            "user": UserResponse.from_orm_user(result["user"]),
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error in staff_login: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Staff login failed: {str(e)}",
        )


# ======================================================
# CURRENT AUTHENTICATED USER
# ======================================================

@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get currently authenticated user's profile",
)
async def get_auth_me(
    current_user: User = Depends(get_current_user),
):
    return UserResponse.from_orm_user(current_user)


# ======================================================
# FORGOT PASSWORD
# ======================================================

@router.post("/forgot-password", response_model=ForgotPasswordResponse, dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def forgot_password(
    request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.forgot_password(
            email=request.email,
            phone=request.phone,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ======================================================
# RESEND FORGOT PASSWORD OTP
# ======================================================

@router.post("/resend-forgot-otp", response_model=ForgotPasswordResponse, dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def resend_forgot_password_otp(
    request: ResendForgotOTPRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.resend_forgot_password_otp(
            email=request.email,
            phone=request.phone,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# ======================================================
# RESET PASSWORD
# ======================================================

@router.post("/reset-password", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def reset_password(
    request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.reset_password(
            email=request.email,
            phone=request.phone,
            otp=request.otp,
            password=request.password,
            confirm_password=request.confirm_password,
        )
    except (InvalidOTPError, OTPExpiredError, MaxAttemptsExceededError) as e:
        _handle_otp_exception(e)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# ======================================================
# CHANGE PASSWORD
# ======================================================

@router.post("/change-password", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def change_password(
    request: ChangePasswordRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):

    try:
        service = AuthService(db)
        result = await service.change_password(
            user_id=user_id,
            current_password=request.current_password,
            new_password=request.new_password,
            confirm_password=request.confirm_password,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# ======================================================
# REFRESH TOKEN
# ======================================================

@router.post("/refresh", response_model=RefreshTokenResponse, dependencies=[Depends(RateLimiter(times=20, seconds=60))])
async def refresh_token(
    response: Response,
    body: RefreshTokenRequest | None = None,
    refresh_token: str | None = Cookie(
        default=None
    ),
    x_refresh_token: str | None = Header(
        default=None, alias="x-refresh-token"
    ),
    db: AsyncSession = Depends(get_db),
):
    token_candidate = None
    if isinstance(refresh_token, str) and refresh_token.strip():
        token_candidate = refresh_token.strip()
    elif body and isinstance(body.refresh_token, str) and body.refresh_token.strip():
        token_candidate = body.refresh_token.strip()
    elif isinstance(x_refresh_token, str) and x_refresh_token.strip():
        token_candidate = x_refresh_token.strip()

    if not token_candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing."
        )
    try:
        service = AuthService(db)
        result = await service.refresh_token(
            token_candidate
        )
        # Replace old cookies
        set_auth_cookies(
            response,
            result["access_token"],
            result["refresh_token"],
        )
        return {
            "message": "Token refreshed successfully.",
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )

# ======================================================
# LOGOUT
# ======================================================

@router.post("/logout", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(
        default=None
    ),
    access_token: str | None = Cookie(
        default=None
    ),
    authorization: str | None = Header(
        default=None
    ),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        extracted_access_token = _extract_token(access_token, authorization)

        await service.logout(
            refresh_token=refresh_token,
            access_token=extracted_access_token
        )
        # Delete cookies
        clear_auth_cookies(response)
        return {
            "message":
            "Logout successful."
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

# ======================================================
# UPDATE PASSWORD WITH OTP (AUTHENTICATED)
# ======================================================

@router.post("/update-password/send-otp", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=3, seconds=60))])
async def send_update_password_otp(
    request: UpdatePasswordSendOTPRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.send_update_password_otp(
            user_id=user_id,
            email=request.email,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/update-password/verify-otp", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def verify_update_password_otp(
    request: UpdatePasswordVerifyOTPRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.verify_update_password_otp(
            user_id=user_id,
            email=request.email,
            otp=request.otp,
        )
    except (InvalidOTPError, OTPExpiredError, MaxAttemptsExceededError) as e:
        _handle_otp_exception(e)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/update-password", response_model=MessageResponse, dependencies=[Depends(RateLimiter(times=5, seconds=60))])
async def update_password(
    request: UpdatePasswordRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AuthService(db)
        return await service.update_password_with_otp(
            user_id=user_id,
            email=request.email,
            new_password=request.new_password,
            confirm_password=request.confirm_password,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )