import secrets
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Endpoints where session cookies are not forged, or external webhooks,
# or where checkout/payment flows are protected by cryptographic signatures and JWT.
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/google",
    "/api/v1/auth/verify-otp",
    "/api/v1/auth/resend-otp",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/resend-forgot-otp",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/refresh",
    "/api/v1/coupons/validate",
    "/api/v1/shipping/calculate",
    "/api/v1/checkout/initiate",
    "/api/v1/payments/verify",
    "/api/v1/orders",
    "/api/v1/chat",  # Stateless AI query — no user data mutation
    "/api/v1/contact",  # Public customer & guest contact form
}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        safe_methods = {"GET", "HEAD", "OPTIONS"}

        if request.method not in safe_methods:
            # Normalize path (strip trailing slashes for robust matching)
            raw_path = request.url.path
            normalized_path = raw_path.rstrip("/") if raw_path != "/" else "/"

            # Skip CSRF check for exempt endpoints, webhooks, and admin/superadmin routes (role-protected)
            if (
                raw_path not in CSRF_EXEMPT_PATHS
                and normalized_path not in CSRF_EXEMPT_PATHS
                and not raw_path.startswith("/api/v1/webhooks")
                and not normalized_path.startswith("/api/v1/webhooks")
                and not raw_path.startswith("/api/v1/admin")
                and not normalized_path.startswith("/api/v1/admin")
                and not raw_path.startswith("/api/v1/superadmin")
                and not normalized_path.startswith("/api/v1/superadmin")
            ):
                # If request has an Authorization: Bearer <token> header, it is an explicit
                # token-authenticated API call. Browsers never automatically attach Bearer headers,
                # so Bearer-authenticated requests cannot be forged via CSRF.
                auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
                is_bearer_auth = bool(auth_header and auth_header.strip().lower().startswith("bearer "))

                if not is_bearer_auth:
                    csrf_cookie = request.cookies.get("csrf_token")
                    csrf_header = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")

                    if (
                        not csrf_cookie
                        or not csrf_header
                        or not secrets.compare_digest(csrf_cookie, csrf_header)
                    ):
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "CSRF token validation failed"}
                        )

        response = await call_next(request)
        return response
