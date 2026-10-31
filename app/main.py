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
                    await autocommit_conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_available BOOLEAN NOT NULL DEFAULT TRUE;"))
                    await autocommit_conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_sample BOOLEAN NOT NULL DEFAULT FALSE;"))
                    await autocommit_conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS sample_price DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0;"))
                    await autocommit_conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS hover_image TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE coupons ADD COLUMN IF NOT EXISTS coupon_type VARCHAR(50) DEFAULT 'CUSTOMER';"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS order_id VARCHAR(36);"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS status_change_count INTEGER DEFAULT 0;"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS admin_notes TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS customer_resolution_feedback VARCHAR(50);"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT FALSE;"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500);"))
                    await autocommit_conn.execute(text("ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS return_request_id VARCHAR(36);"))
                    await autocommit_conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS return_requests (
                            id VARCHAR(36) PRIMARY KEY,
                            order_id VARCHAR(36) NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                            ticket_id VARCHAR(36) REFERENCES support_tickets(id) ON DELETE SET NULL,
                            customer_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                            customer_name VARCHAR(120) NOT NULL,
                            customer_email VARCHAR(255),
                            customer_phone VARCHAR(50),
                            order_amount DOUBLE PRECISION NOT NULL,
                            payment_method VARCHAR(100) NOT NULL,
                            delivery_address JSON NOT NULL,
                            delivered_at TIMESTAMP WITH TIME ZONE NOT NULL,
                            reason VARCHAR(100) NOT NULL,
                            description TEXT NOT NULL,
                            photo_url VARCHAR(500),
                            status VARCHAR(50) NOT NULL DEFAULT 'Pending',
                            admin_notes TEXT,
                            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                        );
                    """))
                    await autocommit_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_requests_order_id ON return_requests(order_id);"))
                    await autocommit_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_return_requests_customer_id ON return_requests(customer_id);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_requests_enabled BOOLEAN NOT NULL DEFAULT TRUE;"))
                    await autocommit_conn.execute(text("ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_window_value INTEGER NOT NULL DEFAULT 30;"))
                    await autocommit_conn.execute(text("ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_window_unit VARCHAR(20) NOT NULL DEFAULT 'minutes';"))
                    await autocommit_conn.execute(text("ALTER TABLE platform_settings ADD COLUMN IF NOT EXISTS return_photo_required BOOLEAN NOT NULL DEFAULT FALSE;"))

                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS returned_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS return_reason TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;"))
                    # UPI QR Code payment support
                    await autocommit_conn.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS qr_code_id VARCHAR(100);"))
                    await autocommit_conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_payments_qr_code_id ON payments (qr_code_id) WHERE qr_code_id IS NOT NULL;"))
                    # Customer Address V2 fields
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS house_number VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS area VARCHAR(150);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS landmark VARCHAR(150);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS district VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS latitude DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS longitude DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS formatted_address VARCHAR(500);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS google_place_id VARCHAR(255);"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS location_source VARCHAR(50) DEFAULT 'MANUAL';"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS location_verified BOOLEAN DEFAULT FALSE;"))
                    await autocommit_conn.execute(text("ALTER TABLE customer_addresses ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE;"))

                    # Orders Dual-Mode Fulfillment & Authoritative Snapshot fields
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS store_location_id VARCHAR(36);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS fulfillment_type VARCHAR(50) DEFAULT 'LOCAL';"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_provider VARCHAR(50) DEFAULT 'INTERNAL';"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS fulfillment_status VARCHAR(50) DEFAULT 'UNASSIGNED';"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_boy_id VARCHAR(36);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_name VARCHAR(120);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_phone VARCHAR(30);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_house_number VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_street VARCHAR(255);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_area VARCHAR(150);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_landmark VARCHAR(150);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_city VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_district VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_state VARCHAR(100);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_pincode VARCHAR(20);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_latitude DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_longitude DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_formatted_address VARCHAR(500);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_google_place_id VARCHAR(255);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_location_source VARCHAR(50);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_location_verified BOOLEAN DEFAULT FALSE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_delivery_charge DOUBLE PRECISION;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_confirmed_at TIMESTAMP WITH TIME ZONE;"))
                    # Delivery Boy OTP & workflow fields
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_otp VARCHAR(6);"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_otp_expires_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_accepted_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_rejected_at TIMESTAMP WITH TIME ZONE;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_rejection_reason TEXT;"))
                    await autocommit_conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_picked_at TIMESTAMP WITH TIME ZONE;"))
                    # Add delivery_boy, delivery_person, super_admin to the user_role enum if not present
                    for val in ["delivery_boy", "delivery_person", "super_admin"]:
                        try:
                            await autocommit_conn.execute(text(f"ALTER TYPE user_role ADD VALUE IF NOT EXISTS '{val}';"))
                        except Exception:
                            pass
                except Exception as e:
                    logger.warning("Inner column migration note: %s", e)

    except Exception as e:
        logger.warning("Database migration note: %s", e)
    # Seed superadmin user
    try:
        from app.services.superadmin_service import ensure_superadmin_exists
        async with AsyncSessionLocal() as db:
            await ensure_superadmin_exists(db)
    except Exception as e:
        logger.warning("Superadmin auto-seed note: %s", e)

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

from app.api.v1.whatsapp_webhook import router as whatsapp_webhook_router
app.include_router(whatsapp_webhook_router)


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
