"""Main API Router Aggregator."""

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    admin_dashboard,
    admin_notifications,
    auth,
    cart,
    categories,
    chat,
    checkout,
    contact,
    coupons,
    customer,
    home,
    orders,
    payments,
    products,
    refunds,
    tickets,
    users,
    webhooks,
    wishlist,
    theme,
    wallet,
    superadmin_overview,
    superadmin_revenue,
    superadmin_sales,
    superadmin_admins,
    superadmin_audit_logs,
    superadmin_theme,
    superadmin_platform_settings,
    superadmin_notifications,
    storage,
)
from app.core.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(storage.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(customer.router)
api_router.include_router(home.router)
api_router.include_router(products.router)
api_router.include_router(categories.router)
api_router.include_router(cart.router)
api_router.include_router(wishlist.router)
api_router.include_router(wallet.router)
api_router.include_router(checkout.router)
api_router.include_router(payments.router)
api_router.include_router(orders.router)
api_router.include_router(webhooks.router)
api_router.include_router(refunds.router)
api_router.include_router(tickets.router)
api_router.include_router(coupons.router)
api_router.include_router(contact.router)
api_router.include_router(chat.router)
api_router.include_router(admin.router)
api_router.include_router(admin_dashboard.router)
api_router.include_router(admin_notifications.router)
api_router.include_router(superadmin_overview.router)
api_router.include_router(superadmin_revenue.router)
api_router.include_router(superadmin_sales.router)
api_router.include_router(superadmin_admins.router)
api_router.include_router(superadmin_audit_logs.router)
api_router.include_router(superadmin_theme.router)
api_router.include_router(superadmin_platform_settings.router)
api_router.include_router(superadmin_notifications.router)
api_router.include_router(theme.router, prefix="/theme", tags=["Theme Builder"])
