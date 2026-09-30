import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import (
    AppError,
    AuthenticationError,
    AuthorizationError,
    MaxAttemptsExceededError,
    OTPError,
)
from app.db.session import AsyncSessionLocal, init_db

# ==========================================================
# Logging Configuration
# ==========================================================

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if not getattr(settings, "DB_ECHO", False):
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# ==========================================================
# Lifespan
# ==========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # Create tables
    try:
        await init_db()
        logger.info("Database tables initialized.")
    except Exception as e:
        logger.error(
            "Database connection failed during startup: %s. "
            "Please check DATABASE_URL in .env and verify your database instance is active and reachable.",
            e,
        )
        raise

    # Additional enum & type migrations for PostgreSQL
    try:
        from sqlalchemy import text
        from app.db.session import engine
        async with engine.connect() as conn:
            autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            if "postgresql" in engine.dialect.name:
                for val in ["Gift Hamper", "Gift Hampers", "Signature"]:
                    try:
                        await autocommit_conn.execute(text(f"ALTER TYPE product_badge ADD VALUE IF NOT EXISTS '{val}';"))
                    except Exception:
                        pass
                try:
                    await autocommit_conn.execute(text("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS coupon_type VARCHAR(50) DEFAULT 'CUSTOMER';"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS order_id VARCHAR(36);"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS status_change_count INTEGER DEFAULT 0;"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS admin_notes TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS customer_resolution_feedback VARCHAR(50);"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT FALSE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS returned_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS return_reason TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;"))
                    # UPI QR Code payment support
                    await autocommit_conn.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS qr_code_id VARCHAR(100);"))
                    await autocommit_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_qr_code_id ON payments (qr_code_id) WHERE qr_code_id IS NOT NULL;"))
                except Exception as ex:
                    logger.warning("Auto migration note: %s", ex)
                logger.info("Database auto-migrations executed successfully.")
    except Exception as e:
        logger.warning("Database migration note: %s", e)






    logger.info("Application startup complete.")
    yield
    logger.info("Application shutting down.")


# ==========================================================
# App
# ==========================================================

from fastapi.responses import HTMLResponse

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    if not settings.DEBUG:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")

    html = f"""<!DOCTYPE html>
<html>
<head>
<link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<link rel="shortcut icon" href="https://fastapi.tiangolo.com/img/favicon.png">
<title>{settings.APP_NAME} - Swagger UI</title>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
<script>
window.onload = function() {{
    window.ui = SwaggerUIBundle({{
        url: '{app.openapi_url}',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIStandalonePreset
        ],
        plugins: [
            SwaggerUIBundle.plugins.DownloadUrl
        ],
        requestInterceptor: function(req) {{
            if (req.method && !['GET', 'HEAD', 'OPTIONS'].includes(req.method.toUpperCase())) {{
                const cookieValue = `; ${{document.cookie}}`;
                const parts = cookieValue.split(`; csrf_token=`);
                if (parts.length === 2) {{
                    const token = parts.pop().split(';').shift();
                    if (token) {{
                        req.headers['X-CSRF-Token'] = token;
                    }}
                }}
            }}
            return req;
        }}
    }});
}};
</script>
</body>
</html>"""
    return HTMLResponse(html)

import os
from app.middleware.csrf_middleware import CSRFMiddleware
from app.middleware.audit import AuditLogMiddleware
from app.middleware.logging_middleware import LoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(AuditLogMiddleware)
app.add_middleware(LoggingMiddleware)

@app.middleware("http")
async def maintenance_mode_middleware(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and not path.startswith("/api/v1/superadmin") and not path.startswith("/api/v1/admin") and not path.startswith("/api/v1/auth") and not path.startswith("/docs") and not path.startswith("/openapi"):
        try:
            async with AsyncSessionLocal() as db:
                from app.repositories.platform_settings_repository import PlatformSettingsRepository
                ps = await PlatformSettingsRepository(db).get()
                if ps and ps.maintenance_mode:
                    return JSONResponse(
                        status_code=503,
                        content={"detail": "Storefront is currently undergoing scheduled maintenance. Please check back soon."},
                    )
        except Exception:
            pass
    return await call_next(request)

# NOTE: Middleware runs in REVERSE order of registration.
# CORS must be added LAST so it executes FIRST (outermost layer),
# ensuring preflight OPTIONS and all error responses include CORS headers.
cors_origins = list(settings.ALLOWED_ORIGINS) if settings.ALLOWED_ORIGINS else []
for fallback_origin in [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]:
    if fallback_origin not in cors_origins:
        cors_origins.append(fallback_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=r"^https://(.*\.railway\.app|.*\.up\.railway\.app|chovique(-[a-zA-Z0-9_-]+)?\.vercel\.app)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for local uploads fallback
from pathlib import Path
from fastapi.staticfiles import StaticFiles

static_dir = Path("static")
static_dir.mkdir(exist_ok=True)
(static_dir / "uploads").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(api_router)


# ==========================================================
# Global Exception Handlers
# ==========================================================

@app.exception_handler(MaxAttemptsExceededError)
async def max_attempts_handler(request: Request, exc: MaxAttemptsExceededError):
    return JSONResponse(
        status_code=429,
        content={"detail": exc.message},
    )


@app.exception_handler(OTPError)
async def otp_error_handler(request: Request, exc: OTPError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )


@app.exception_handler(AuthenticationError)
async def auth_error_handler(request: Request, exc: AuthenticationError):
    return JSONResponse(
        status_code=401,
        content={"detail": exc.message},
    )


@app.exception_handler(AuthorizationError)
async def authz_error_handler(request: Request, exc: AuthorizationError):
    return JSONResponse(
        status_code=403,
        content={"detail": exc.message},
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message},
    )


# ==========================================================
# Health Check
# ==========================================================

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/", include_in_schema=False)
def read_root():
    return {"message": "Welcome to Chovique API. Please use /api/v1 endpoints."}
