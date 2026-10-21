import logging
from typing import Optional

from fastapi import Cookie, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.db.redis import redis_client

logger = logging.getLogger(__name__)


def _extract_tokens(
    access_token: Optional[str],
    authorization: Optional[str],
) -> list[str]:
    """
    Extract candidate tokens from Authorization header and/or access_token cookie.
    Authorization Bearer header is prioritized as it reflects the client's current runtime state,
    followed by the cookie.
    """
    tokens: list[str] = []
    if isinstance(authorization, str) and authorization.lower().startswith("bearer "):
        bearer_val = authorization.split(" ", 1)[1].strip()
        if bearer_val:
            tokens.append(bearer_val)
    if isinstance(access_token, str) and access_token and access_token not in tokens:
        tokens.append(access_token)
    return tokens


def _extract_token(
    access_token: Optional[str],
    authorization: Optional[str],
) -> Optional[str]:
    """Accept either the httponly access_token cookie or a Bearer header (backwards-compatible helper)."""
    tokens = _extract_tokens(access_token, authorization)
    return tokens[0] if tokens else None


async def get_current_user_id(
    access_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
) -> str:
    """
    Resolve the authenticated user's id from the access token.

    Supports both the httponly `access_token` cookie (set by the backend on
    login/register) and an `Authorization: Bearer <token>` header, testing candidate
    tokens gracefully so stale cookies do not shadow fresh client bearer tokens.
    """
    tokens = _extract_tokens(access_token, authorization)

    if not tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    last_error_status = status.HTTP_401_UNAUTHORIZED
    last_error_detail = "Invalid or expired access token."

    for token in tokens:
        payload = decode_token(token)
        if not payload:
            continue

        try:
            is_blocked = await redis_client.get(f"blocklist:{token}")
        except Exception as e:
            logger.error("Token revocation verification failed due to Redis service disruption: %s", e)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service is temporarily unavailable. Please try again.",
            )

        if is_blocked:
            last_error_detail = "Token has been revoked."
            continue

        if payload.get("type") != "access":
            last_error_detail = "Invalid token type."
            continue

        user_id = payload.get("sub")
        if not user_id:
            last_error_detail = "Invalid token payload."
            continue

        return user_id

    raise HTTPException(
        status_code=last_error_status,
        detail=last_error_detail,
    )


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the full, active User record for the authenticated request."""

    user = await UserRepository(db).get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )

    return user


async def get_current_user_optional(
    access_token: Optional[str] = Cookie(default=None),
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Attempt to resolve the authenticated user, or return None if unauthenticated.
    """
    token = _extract_token(access_token, authorization)
    if not token:
        return None
    try:
        user_id = await get_current_user_id(access_token=access_token, authorization=authorization)
        return await UserRepository(db).get_by_id(user_id)
    except Exception:
        return None


# ==========================================================
# Role-Based Access Control
# ==========================================================

def require_role(*allowed_roles):
    """
    Dependency factory that returns a dependency requiring
    the current user to have one of the specified roles.

    Accepts single string arguments, lists, tuples, or sets.
    """
    roles_set = set()
    for role in allowed_roles:
        if isinstance(role, (list, tuple, set)):
            roles_set.update(str(r).lower().strip() for r in role)
        else:
            roles_set.add(str(role).lower().strip())

    async def _check_role(
        current_user: User = Depends(get_current_user),
    ) -> User:
        user_role = (current_user.role or "").lower().strip()
        if user_role not in roles_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )
        return current_user

    return _check_role


# Convenience shortcut for admin-only routes
get_current_admin = require_role("admin", "superadmin")
