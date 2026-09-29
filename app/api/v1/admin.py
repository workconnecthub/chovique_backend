import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, and_, distinct, text, inspect
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.schemas.admin import (
    AdminOrderListResponse,
    AuditLogEntry,
    BannerImageResponse,
    CreateAdminRequest,
    CreateBannerRequest,
    UpdateBannerRequest,
    CreateReelRequest,
    CreateTestimonialRequest,
    DashboardStatsResponse,
    FulfillmentStatusPayload,
    ImportSalesResponse,
    OfflineSalePayload,
    OfflineSaleResponse,
    PaymentStatusPayload,
    ReelResponse,
    ResolveTicketPayload,
    SetContactRequest,
    SetStatsRequest,
    UpdateAdminPasswordPayload,
    UpdateAdminRequest,
    UpdateOrderStatusPayload,
    CustomerDetailsResponse,
    CustomerUpdatePayload,
    CustomerListPaginatedResponse,
    CustomerCoinsResponse,
)
from app.schemas.home import BannerResponse, ContactInfoResponse, StatsResponse, TestimonialResponse
from app.schemas.order import OrderResponse
from app.schemas.reports import ReportQueryRequest, ReportResponse
from app.schemas.ticket import SupportTicketResponse, UpdateTicketStatusPayload
from app.schemas.user import SystemUserResponse
from app.services.report_service import ReportService
from app.services.excel_report_service import ExcelReportService
from app.services.pdf_report_service import PdfReportService
from app.services.csv_report_service import CsvReportService
from app.schemas.category import AdminCategoryResponse, CategoryUpdate
from app.services.admin_service import AdminService
from app.schemas.wallet import RewardSettingsSchema, CoinTransactionResponse, AdminCustomerRewardStat, AdminCoinTransactionItem
from app.services.wallet_service import WalletService
from app.models.audit_log import AuditLog
from app.schemas.admin_profile import AdminProfileResponse, AdminProfileUpdateRequest
from sqlalchemy import select, func, and_

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin Module"])


# ======================================================
# ADMIN MY PROFILE
# ======================================================

@router.get("/profile", response_model=AdminProfileResponse, summary="Get authenticated admin profile")
async def get_admin_profile(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    return AdminProfileResponse.model_validate(current_user)


@router.put("/profile", response_model=AdminProfileResponse, summary="Update authenticated admin profile")
async def update_admin_profile(
    payload: AdminProfileUpdateRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # Check email uniqueness against other users
    if payload.email.lower() != current_user.email.lower():
        existing = await db.execute(
            select(User).where(func.lower(User.email) == payload.email.lower(), User.id != current_user.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email address is already registered by another account.",
            )

    # Perform updates (strictly full_name, email, phone, address — NEVER role/permissions/password)
    current_user.full_name = payload.full_name.strip()
    current_user.email = payload.email.lower().strip()
    current_user.phone = payload.phone.strip()
    current_user.address = payload.address.strip()

    # Create Audit Log record & Activity Log
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="UPDATE_ADMIN_PROFILE",
        resource="admin_profile",
        details=f"Admin updated profile details: Name='{current_user.full_name}', Email='{current_user.email}', Phone='{current_user.phone}'",
    )
    db.add(audit_entry)

    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="UPDATED_PROFILE",
        module="profile",
        description=f"Admin '{current_user.full_name}' updated profile info.",
    )

    await db.commit()
    await db.refresh(current_user)
    return AdminProfileResponse.model_validate(current_user)


from app.schemas.user import AvatarUploadResponse
from app.services.customer_service import CustomerService

@router.post("/profile/avatar", response_model=AvatarUploadResponse, summary="Upload authenticated admin profile avatar")
async def upload_admin_avatar(
    avatar: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    allowed_mimes = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    filename = avatar.filename or ""
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if (avatar.content_type and avatar.content_type.lower() not in allowed_mimes) and ext not in ["jpg", "jpeg", "png", "webp"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image format. Only JPG, JPEG, PNG, and WebP formats are allowed.",
        )
    service = CustomerService(db)
    return await service.upload_avatar(current_user.id, avatar)


# ======================================================
# ADMIN CHANGE PASSWORD
# ======================================================

from app.core.security import verify_password, hash_password
from app.models.refresh_token import RefreshToken
from app.schemas.change_password import AdminChangePasswordRequest
from sqlalchemy import delete


@router.post("/change-password", summary="Change admin password")
async def change_admin_password(
    payload: AdminChangePasswordRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # 1. Verify current password using secure password hashing
    if not current_user.hashed_password or not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    # 2. Reject if new password equals current password
    if verify_password(payload.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password cannot be the same as your current password.",
        )

    # 3. Hash new password securely
    new_hash = hash_password(payload.new_password)
    current_user.hashed_password = new_hash

    # 4. Invalidate existing sessions according to security policy
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == current_user.id))

    # 5. Create audit log & activity log
    audit_entry = AuditLog(
        user_id=current_user.id,
        action="CHANGE_ADMIN_PASSWORD",
        resource="security",
        details=f"Admin {current_user.email} successfully changed password. Active refresh tokens invalidated.",
    )
    db.add(audit_entry)

    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="CHANGED_PASSWORD",
        module="security",
        description=f"Admin '{current_user.full_name}' ({current_user.email}) changed password.",
    )

    await db.commit()
    return {"message": "Password changed successfully. Please log in again with your new password."}


# ======================================================
# ADMIN ACTIVITY LOGS (READ-ONLY)
# ======================================================

from app.schemas.admin_activity_log import ActivityLogListResponse
from app.services.activity_log_service import ActivityLogService, log_admin_activity


@router.get("/activity-logs", response_model=ActivityLogListResponse, summary="Get immutable admin activity logs")
async def get_admin_activity_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    module: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = ActivityLogService(db)
    return await service.get_activity_logs(
        page=page,
        limit=limit,
        start_date=start_date,
        end_date=end_date,
        module=module,
        action=action,
        status=status,
        search=search,
    )


# ======================================================
# ADMIN LOGOUT
# ======================================================

from fastapi import Response


@router.post("/logout", summary="Secure admin logout")
async def admin_logout(
    response: Response,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    # 1. Invalidate/revoke session in DB
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == current_user.id))

    # 2. Clear authentication cookies
    is_prod = not settings.DEBUG
    samesite_mode = "none" if is_prod else "lax"
    secure_mode = is_prod

    response.delete_cookie(key="access_token", httponly=True, secure=secure_mode, samesite=samesite_mode)
    response.delete_cookie(key="refresh_token", httponly=True, secure=secure_mode, samesite=samesite_mode)

    # 3. Log activity
    await log_admin_activity(
        db=db,
        admin_id=current_user.id,
        action="LOGGED_OUT",
        module="auth",
        description=f"Admin '{current_user.full_name}' ({current_user.email}) logged out securely.",
    )

    await db.commit()
    return {"message": "Logged out successfully."}


# ======================================================
# REWARD SYSTEM MANAGEMENT
# ======================================================

@router.get("/rewards/settings", response_model=RewardSettingsSchema, summary="Get reward system settings")
async def get_reward_settings(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = WalletService(db)
    return await service.get_reward_settings()


@router.get("/rewards/customers", response_model=List[AdminCustomerRewardStat], summary="Get customer reward overview")
async def get_admin_customer_rewards(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User
    from app.models.order import Order
    from app.models.wallet import CoinTransaction
    from sqlalchemy import select, func

    user_stmt = select(User).where(User.role == "customer").order_by(User.created_at.desc())
    users = (await db.execute(user_stmt)).scalars().all()

    wallet_svc = WalletService(db)
    results = []

    for user in users:
        summary = await wallet_svc.compute_user_coin_summary(user.id)
        
        fb_cnt = await db.scalar(
            select(func.count(CoinTransaction.id)).where(
                CoinTransaction.user_id == user.id,
                CoinTransaction.type == "FIRST_ORDER_BONUS"
            )
        ) or 0
        
        if fb_cnt > 0:
            fo_status = "Awarded"
        else:
            order_cnt = await db.scalar(
                select(func.count(Order.id)).where(
                    Order.user_id == user.id,
                    Order.status.notin_(["Cancelled", "CANCELLED"])
                )
            ) or 0
            if order_cnt == 0:
                fo_status = "Eligible"
            else:
                fo_status = "Not Eligible"

        results.append(
            AdminCustomerRewardStat(
                user_id=user.id,
                customer_name=user.full_name or "Customer",
                customer_email=user.email,
                available_coins=summary["available_coins"],
                pending_coins=summary["pending_coins"],
                total_coins_earned=summary["total_earned"],
                total_coins_redeemed=summary["total_redeemed"],
                total_coins_returned=summary["total_returned"],
                total_coins_reversed=summary["total_reversed"],
                first_order_bonus_status=fo_status,
            )
        )

    return results


@router.get("/rewards/transactions", response_model=List[AdminCoinTransactionItem], summary="Get all coin transactions")
async def get_admin_coin_transactions(
    type_filter: Optional[str] = None,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.models.user import User
    from app.models.order import Order
    from app.models.wallet import CoinTransaction
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select

    wallet_svc = WalletService(db)
    settings = await wallet_svc.get_reward_settings()
    delay_hours = getattr(settings, "credit_delay_hours", 24) or 24
    now_utc = datetime.now(timezone.utc)

    query = select(CoinTransaction, User).outerjoin(User, CoinTransaction.user_id == User.id)
    if type_filter and type_filter.upper() != "ALL":
        query = query.where(CoinTransaction.type == type_filter.upper())
    query = query.order_by(CoinTransaction.created_at.desc()).limit(200)

    rows = (await db.execute(query)).all()
    results = []

    for tx, user in rows:
        t_type = (tx.type or "").upper()
        t_dt = tx.created_at
        if t_dt and t_dt.tzinfo is None:
            t_dt = t_dt.replace(tzinfo=timezone.utc)

        status = "Completed"
        available_at_str = None
        
        if t_type in ("EARN", "ORDER_REWARD", "FIRST_ORDER_BONUS") and tx.order_id:
            ord_obj = await db.get(Order, tx.order_id)
            if ord_obj and (ord_obj.status or "").lower() in ("cancelled",):
                status = "Reversed"
                available_at_str = None
            else:
                avail_dt = t_dt + timedelta(hours=delay_hours) if t_dt else None
                if t_dt and (now_utc < avail_dt):
                    status = "Pending"
                    available_at_str = avail_dt.strftime("%d %b %Y, %I:%M %p")
                else:
                    status = "Credited"
        elif t_type in ("WELCOME", "ACCOUNT_CREATION"):
            status = "Credited"
        elif t_type in ("REDEEM", "COIN_REDEMPTION"):
            status = "Redeemed"
        elif t_type in ("REFUND", "RETURN", "COIN_RETURN"):
            status = "Returned"
        elif t_type in ("ADJUSTMENT", "REVERSAL", "COIN_REVERSAL"):
            status = "Reversed"

        type_display = {
            "WELCOME": "Account Creation Reward",
            "ACCOUNT_CREATION": "Account Creation Reward",
            "FIRST_ORDER_BONUS": "First Order Bonus",
            "ORDER_REWARD": "Order Reward",
            "EARN": "Order Reward",
            "REDEEM": "Coin Redemption",
            "COIN_REDEMPTION": "Coin Redemption",
            "REFUND": "Coin Return",
            "RETURN": "Coin Return",
            "COIN_RETURN": "Coin Return",
            "ADJUSTMENT": "Coin Reversal",
            "REVERSAL": "Coin Reversal",
            "COIN_REVERSAL": "Coin Reversal",
        }.get(t_type, t_type)

        results.append(
            AdminCoinTransactionItem(
                id=tx.id,
                customer_name=user.full_name if user else "Unknown",
                customer_email=user.email if user else "N/A",
                coins=tx.coins,
                transaction_type=type_display,
                status=status,
                reason=tx.description or "Coin Activity",
                order_id=tx.order_id,
                created_at=t_dt.strftime("%d %b %Y, %I:%M %p") if t_dt else "",
                available_at=available_at_str,
            )
        )

    return results


# ======================================================
# REPORTS & ANALYTICS EXPORTS
# ======================================================

@router.get("/reports/customers/export/excel", summary="Export customer report to Excel (admin only)")
async def export_customers_excel(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        # Load summary KPIs
        req = ReportQueryRequest(report_type="customers", start_date=start_date, end_date=end_date)
        summary_res = await service.generate_report(req)
        
        # Get all records for range
        query = (
            select(
                User.full_name,
                User.email,
                User.phone,
                func.count(Order.id).label("orders_cnt"),
                func.coalesce(func.sum(Order.total), 0.0).label("total_spent"),
                User.created_at
            )
            .select_from(User)
            .outerjoin(Order, and_(User.id == Order.user_id, Order.status != "CANCELLED", Order.status != "Cancelled"))
            .where(User.created_at >= start_dt, User.created_at <= end_dt)
            .group_by(User.id, User.full_name, User.email, User.phone, User.created_at)
            .order_by(User.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        customers_data = []
        for row in res:
            customers_data.append([
                row.full_name or "Unnamed Customer",
                row.email,
                row.phone or "N/A",
                row.orders_cnt,
                row.total_spent,
                row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
            ])
            
        excel_buffer = ExcelReportService.generate_customer_report(
            start_date=start_date,
            end_date=end_date,
            kpis=summary_res.kpi_summary,
            customers=customers_data
        )
        
        filename = f"customer_report_{start_date}_to_{end_date}.xlsx"
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Customer Excel export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export customer report.")


@router.get("/reports/customers/export/pdf", summary="Export customer report to PDF (admin only)")
async def export_customers_pdf(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        # Load summary KPIs
        req = ReportQueryRequest(report_type="customers", start_date=start_date, end_date=end_date)
        summary_res = await service.generate_report(req)
        
        query = (
            select(
                User.full_name,
                User.email,
                User.phone,
                func.count(Order.id).label("orders_cnt"),
                func.coalesce(func.sum(Order.total), 0.0).label("total_spent"),
                User.created_at
            )
            .select_from(User)
            .outerjoin(Order, and_(User.id == Order.user_id, Order.status != "CANCELLED", Order.status != "Cancelled"))
            .where(User.created_at >= start_dt, User.created_at <= end_dt)
            .group_by(User.id, User.full_name, User.email, User.phone, User.created_at)
            .order_by(User.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        customers_data = []
        for row in res:
            customers_data.append([
                row.full_name or "Unnamed Customer",
                row.email,
                row.phone or "N/A",
                str(row.orders_cnt),
                f"₹{row.total_spent:,.2f}",
                row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
            ])
            
        pdf_buffer = PdfReportService.generate_customer_report(
            start_date=start_date,
            end_date=end_date,
            kpis=summary_res.kpi_summary,
            customers=customers_data
        )
        
        filename = f"customer_report_{start_date}_to_{end_date}.pdf"
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Customer PDF export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export customer report.")


@router.get("/reports/customers/export/csv", summary="Export customer report to CSV (admin only)")
async def export_customers_csv(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(
                User.full_name,
                User.email,
                User.phone,
                func.count(Order.id).label("orders_cnt"),
                func.coalesce(func.sum(Order.total), 0.0).label("total_spent"),
                User.created_at
            )
            .select_from(User)
            .outerjoin(Order, and_(User.id == Order.user_id, Order.status != "CANCELLED", Order.status != "Cancelled"))
            .where(User.created_at >= start_dt, User.created_at <= end_dt)
            .group_by(User.id, User.full_name, User.email, User.phone, User.created_at)
            .order_by(User.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        headers = ["Customer Name", "Email", "Phone", "Orders Placed", "Total Spend", "Joined Date"]
        rows = []
        for row in res:
            rows.append([
                row.full_name or "Unnamed Customer",
                row.email,
                row.phone or "N/A",
                row.orders_cnt,
                row.total_spent,
                row.created_at.strftime("%Y-%m-%d") if row.created_at else ""
            ])
            
        csv_buffer = CsvReportService.generate_csv(headers, rows)
        filename = f"customer_report_{start_date}_to_{end_date}.csv"
        return StreamingResponse(
            csv_buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Customer CSV export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export customer report.")


@router.get("/reports/orders/export/excel", summary="Export orders report to Excel (admin only)")
async def export_orders_excel(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(Order, User)
            .options(selectinload(Order.items))
            .outerjoin(User, Order.user_id == User.id)
            .where(Order.created_at >= start_dt, Order.created_at <= end_dt)
            .order_by(Order.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        orders_data = []
        for o, u in res:
            cust_name = u.full_name if u else "Guest Customer"
            cust_email = u.email if u else "N/A"
            if not u and isinstance(o.shipping_address, dict):
                cust_name = o.shipping_address.get("full_name") or o.shipping_address.get("name") or "Guest Customer"
                cust_email = o.shipping_address.get("email") or "N/A"
                
            state = inspect(o)
            items_cnt = len(o.items) if state and "items" not in state.unloaded and o.items else 1
            
            orders_data.append([
                o.id,
                cust_name,
                cust_email,
                o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                items_cnt,
                o.subtotal or 0.0,
                o.discount or 0.0,
                o.shipping or 0.0,
                o.tax or 0.0,
                o.total or 0.0,
                o.payment_status or "PENDING",
                o.status or "Processing"
            ])
            
        excel_buffer = ExcelReportService.generate_orders_report(
            start_date=start_date,
            end_date=end_date,
            orders=orders_data
        )
        
        filename = f"orders_report_{start_date}_to_{end_date}.xlsx"
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Orders Excel export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export orders report.")


@router.get("/reports/orders/export/pdf", summary="Export orders report to PDF (admin only)")
async def export_orders_pdf(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(Order, User)
            .options(selectinload(Order.items))
            .outerjoin(User, Order.user_id == User.id)
            .where(Order.created_at >= start_dt, Order.created_at <= end_dt)
            .order_by(Order.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        orders_data = []
        for o, u in res:
            cust_name = u.full_name if u else "Guest"
            cust_email = u.email if u else "N/A"
            if not u and isinstance(o.shipping_address, dict):
                cust_name = o.shipping_address.get("full_name") or o.shipping_address.get("name") or "Guest"
                cust_email = o.shipping_address.get("email") or "N/A"
                
            state = inspect(o)
            items_cnt = len(o.items) if state and "items" not in state.unloaded and o.items else 1
            
            orders_data.append([
                o.id[:8],
                cust_name,
                cust_email,
                o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                str(items_cnt),
                f"₹{o.subtotal:,.2f}",
                f"₹{o.discount:,.2f}",
                f"₹{o.shipping:,.2f}",
                f"₹{o.tax:,.2f}",
                f"₹{o.total:,.2f}",
                o.payment_status or "PENDING",
                o.status or "Processing"
            ])
            
        pdf_buffer = PdfReportService.generate_orders_report(
            start_date=start_date,
            end_date=end_date,
            orders=orders_data
        )
        
        filename = f"orders_report_{start_date}_to_{end_date}.pdf"
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Orders PDF export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export orders report.")


@router.get("/reports/orders/export/csv", summary="Export orders report to CSV (admin only)")
async def export_orders_csv(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(Order, User)
            .options(selectinload(Order.items))
            .outerjoin(User, Order.user_id == User.id)
            .where(Order.created_at >= start_dt, Order.created_at <= end_dt)
            .order_by(Order.created_at.desc())
        )
        res = (await db.execute(query)).all()
        
        headers = [
            "Order ID", "Customer Name", "Customer Email", "Order Date", "Number of Items",
            "Subtotal", "Discount", "Shipping", "Tax", "Total Amount", "Payment Status", "Order Status"
        ]
        
        rows = []
        for o, u in res:
            cust_name = u.full_name if u else "Guest Customer"
            cust_email = u.email if u else "N/A"
            if not u and isinstance(o.shipping_address, dict):
                cust_name = o.shipping_address.get("full_name") or o.shipping_address.get("name") or "Guest Customer"
                cust_email = o.shipping_address.get("email") or "N/A"
                
            state = inspect(o)
            items_cnt = len(o.items) if state and "items" not in state.unloaded and o.items else 1
            
            rows.append([
                o.id,
                cust_name,
                cust_email,
                o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else "",
                items_cnt,
                o.subtotal or 0.0,
                o.discount or 0.0,
                o.shipping or 0.0,
                o.tax or 0.0,
                o.total or 0.0,
                o.payment_status or "PENDING",
                o.status or "Processing"
            ])
            
        csv_buffer = CsvReportService.generate_csv(headers, rows)
        filename = f"orders_report_{start_date}_to_{end_date}.csv"
        return StreamingResponse(
            csv_buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Orders CSV export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export orders report.")


@router.get("/reports/products/export/excel", summary="Export product report to Excel (admin only)")
async def export_products_excel(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(
                Product.name,
                Product.category,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
                func.count(distinct(Order.id)).label("total_orders"),
                func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0.0).label("revenue"),
                Product.stock
            )
            .select_from(OrderItem)
            .join(Product, OrderItem.product_id == Product.id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.created_at >= start_dt,
                Order.created_at <= end_dt,
                Order.status != "CANCELLED",
                Order.status != "Cancelled"
            )
            .group_by(Product.id, Product.name, Product.category, Product.stock)
            .order_by(text("revenue DESC"))
        )
        res = (await db.execute(query)).all()
        
        products_data = []
        for row in res:
            products_data.append([
                row.name,
                row.category or "Gourmet Chocolates",
                row.units_sold,
                row.total_orders,
                row.revenue,
                0.0,  # ASP calculated inside Service
                row.stock
            ])
            
        excel_buffer = ExcelReportService.generate_products_report(
            start_date=start_date,
            end_date=end_date,
            products=products_data
        )
        
        filename = f"product_report_{start_date}_to_{end_date}.xlsx"
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Product Excel export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export product report.")


@router.get("/reports/products/export/csv", summary="Export product report to CSV (admin only)")
async def export_products_csv(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        query = (
            select(
                Product.name,
                Product.category,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
                func.count(distinct(Order.id)).label("total_orders"),
                func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0.0).label("revenue"),
                Product.stock
            )
            .select_from(OrderItem)
            .join(Product, OrderItem.product_id == Product.id)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.created_at >= start_dt,
                Order.created_at <= end_dt,
                Order.status != "CANCELLED",
                Order.status != "Cancelled"
            )
            .group_by(Product.id, Product.name, Product.category, Product.stock)
            .order_by(text("revenue DESC"))
        )
        res = (await db.execute(query)).all()
        
        headers = ["Product Name", "Category", "Units Sold", "Total Orders", "Revenue", "Average Selling Price", "Stock Status"]
        rows = []
        for row in res:
            avg_price = row.revenue / row.units_sold if row.units_sold > 0 else 0.0
            rows.append([
                row.name,
                row.category or "Gourmet Chocolates",
                row.units_sold,
                row.total_orders,
                row.revenue,
                avg_price,
                row.stock
            ])
            
        csv_buffer = CsvReportService.generate_csv(headers, rows)
        filename = f"product_report_{start_date}_to_{end_date}.csv"
        return StreamingResponse(
            csv_buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Product CSV export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export product report.")


@router.get("/reports/analytics/export/excel", summary="Export analytics report to Excel (admin only)")
async def export_analytics_excel(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        # Aggregate detailed counts & sums
        ord_q = select(
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
            func.coalesce(func.sum(Order.discount), 0.0),
            func.coalesce(func.sum(Order.tax), 0.0),
            func.coalesce(func.sum(Order.shipping), 0.0)
        ).where(Order.created_at >= start_dt, Order.created_at <= end_dt, Order.status != "CANCELLED", Order.status != "Cancelled")
        
        tot_rev, ord_cnt, disc_tot, tax_tot, ship_tot = (await db.execute(ord_q)).first()
        
        cust_q = select(func.count(User.id)).where(User.created_at >= start_dt, User.created_at <= end_dt, User.role == "customer")
        cust_cnt = (await db.execute(cust_q)).scalar() or 0
        
        total_cust_q = select(func.count(User.id)).where(User.role == "customer")
        total_cust = (await db.execute(total_cust_q)).scalar() or 0
        
        prod_q = select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order, OrderItem.order_id == Order.id).where(Order.created_at >= start_dt, Order.created_at <= end_dt, Order.status != "CANCELLED", Order.status != "Cancelled")
        prod_cnt = (await db.execute(prod_q)).scalar() or 0
        
        avg_val = tot_rev / ord_cnt if ord_cnt > 0 else 0.0
        
        # Prepare data dict
        summary_data = {
            "total_revenue": tot_rev,
            "total_orders": ord_cnt,
            "total_customers": total_cust,
            "new_customers": cust_cnt,
            "repeat_customers": max(0, total_cust - cust_cnt),
            "avg_order_value": avg_val,
            "total_products_sold": prod_cnt,
            "total_discounts": disc_tot,
            "total_tax": tax_tot,
            "total_shipping_revenue": ship_tot,
            "daily_trend": []
        }
        
        # Generate daily trend tuples
        curr = start_dt.date()
        end_d = end_dt.date()
        while curr <= end_d:
            d_start = datetime.combine(curr, datetime.min.time())
            d_end = datetime.combine(curr, datetime.max.time())
            day_q = select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0.0)).where(Order.created_at >= d_start, Order.created_at <= d_end, Order.status != "CANCELLED", Order.status != "Cancelled")
            d_cnt, d_rev = (await db.execute(day_q)).first()
            summary_data["daily_trend"].append((curr.strftime("%Y-%m-%d"), d_cnt or 0, d_rev or 0.0))
            curr += timedelta(days=1)
            
        excel_buffer = ExcelReportService.generate_analytics_report(
            start_date=start_date,
            end_date=end_date,
            summary_data=summary_data
        )
        
        filename = f"analytics_report_{start_date}_to_{end_date}.xlsx"
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Analytics Excel export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export analytics report.")


@router.get("/reports/analytics/export/pdf", summary="Export analytics report to PDF (admin only)")
async def export_analytics_pdf(
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        start_dt, end_dt = service._parse_date_range(start_date, end_date)
        
        ord_q = select(
            func.coalesce(func.sum(Order.total), 0.0),
            func.count(Order.id),
            func.coalesce(func.sum(Order.discount), 0.0),
            func.coalesce(func.sum(Order.tax), 0.0),
            func.coalesce(func.sum(Order.shipping), 0.0)
        ).where(Order.created_at >= start_dt, Order.created_at <= end_dt, Order.status != "CANCELLED", Order.status != "Cancelled")
        
        tot_rev, ord_cnt, disc_tot, tax_tot, ship_tot = (await db.execute(ord_q)).first()
        
        cust_q = select(func.count(User.id)).where(User.created_at >= start_dt, User.created_at <= end_dt, User.role == "customer")
        cust_cnt = (await db.execute(cust_q)).scalar() or 0
        
        total_cust_q = select(func.count(User.id)).where(User.role == "customer")
        total_cust = (await db.execute(total_cust_q)).scalar() or 0
        
        prod_q = select(func.coalesce(func.sum(OrderItem.quantity), 0)).join(Order, OrderItem.order_id == Order.id).where(Order.created_at >= start_dt, Order.created_at <= end_dt, Order.status != "CANCELLED", Order.status != "Cancelled")
        prod_cnt = (await db.execute(prod_q)).scalar() or 0
        
        avg_val = tot_rev / ord_cnt if ord_cnt > 0 else 0.0
        
        summary_data = {
            "total_revenue": tot_rev,
            "total_orders": ord_cnt,
            "total_customers": total_cust,
            "new_customers": cust_cnt,
            "repeat_customers": max(0, total_cust - cust_cnt),
            "avg_order_value": avg_val,
            "total_products_sold": prod_cnt,
            "total_discounts": disc_tot,
            "total_tax": tax_tot,
            "total_shipping_revenue": ship_tot,
        }
        
        pdf_buffer = PdfReportService.generate_analytics_report(
            start_date=start_date,
            end_date=end_date,
            summary_data=summary_data
        )
        
        filename = f"analytics_report_{start_date}_to_{end_date}.pdf"
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Analytics PDF export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export analytics report.")


@router.put("/rewards/settings", response_model=RewardSettingsSchema, summary="Update reward system settings")
async def update_reward_settings(
    payload: RewardSettingsSchema,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = WalletService(db)
    return await service.update_reward_settings(payload)



# ======================================================
# REPORTS & ANALYTICS
# ======================================================

@router.get("/reports", response_model=ReportResponse, summary="Generate business reports (admin only)")
async def generate_report(
    report_type: str = Query(..., description="sales, orders, products, customers, coupons, reward_coins"),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        req = ReportQueryRequest(
            report_type=report_type.lower(),
            start_date=start_date,
            end_date=end_date,
            page=page,
            limit=limit,
        )
        service = ReportService(db)
        return await service.generate_report(req)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Report generation failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to generate report.")


@router.get("/reports/export", summary="Export report as CSV (admin only)")
async def export_report_csv(
    report_type: str = Query(..., description="sales, orders, products, customers, coupons, reward_coins"),
    start_date: str = Query(..., description="Start date YYYY-MM-DD"),
    end_date: str = Query(..., description="End date YYYY-MM-DD"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = ReportService(db)
        csv_buffer = await service.export_report_csv(
            report_type=report_type.lower(),
            start_date=start_date,
            end_date=end_date,
        )
        filename = f"chovique_{report_type}_report_{start_date}_to_{end_date}.csv"
        return StreamingResponse(
            csv_buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error("Report CSV export failed: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to export CSV report.")


# ======================================================
# DASHBOARD STATS
# ======================================================

@router.get(
    "/audit-logs",
    response_model=list[AuditLogEntry],
    summary="Get recent audit log entries (superadmin only)",
)
async def get_audit_logs(
    limit: int = 50,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_audit_logs(limit=limit)


from datetime import date

@router.get(
    "/stats",
    response_model=DashboardStatsResponse,
    summary="Get admin dashboard analytics stats",
)
async def get_dashboard_stats(
    preset: Optional[str] = Query(None, description="Preset filter: today, 7days, 30days, thisMonth, custom"),
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start date cannot be after end date.",
        )
    service = AdminService(db)
    return await service.get_dashboard_stats(preset=preset, start_date=start_date, end_date=end_date)


# ======================================================
# COUPONS
# ======================================================

from app.schemas.coupon import CouponCreate, CouponUpdate, CouponAdminResponse

@router.get(
    "/coupons",
    response_model=list[CouponAdminResponse],
    summary="Get all coupons (admin only)",
)
async def get_all_coupons(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_coupons()

@router.post(
    "/coupons",
    response_model=CouponAdminResponse,
    summary="Create a new coupon (admin only)",
)
async def create_coupon(
    payload: CouponCreate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        coupon = await service.create_coupon(payload)
        if not coupon:
            raise HTTPException(status_code=400, detail="Failed to create coupon")
        return coupon
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.patch(
    "/coupons/{code}",
    response_model=CouponAdminResponse,
    summary="Update a coupon (admin only)",
)
async def update_coupon(
    code: str,
    payload: CouponUpdate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    coupon = await service.update_coupon(code, payload)
    if not coupon:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return coupon

@router.delete(
    "/coupons/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a coupon (admin only)",
)
async def delete_coupon(
    code: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    await service.delete_coupon(code)

@router.delete(
    "/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product (admin only)",
)
async def delete_product(
    product_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.product_service import ProductService
    service = ProductService(db)
    await service.delete_product(product_id)


@router.patch(
    "/products/{product_id}/stock",
    summary="Update product stock directly",
)
async def update_product_stock(
    product_id: str,
    payload: dict,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from app.services.product_service import ProductService
    service = ProductService(db)
    stock = payload.get("stock", 0)
    
    # We update it via the product repository
    product = await service.product_repo.get_by_id(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
        
    old_stock = product.stock
    await service.product_repo.update(product_id, stock=stock)
    
    # Log stock change to audit logs
    from app.repositories.audit_log_repository import AuditLogRepository
    audit_repo = AuditLogRepository(db)
    await audit_repo.log(
        action="update_product_stock",
        user_id=current_user.id,
        resource=f"product:{product_id}",
        details=f"Stock adjusted from {old_stock} to {stock} by {current_user.email}",
    )
    return {"message": "Stock updated successfully", "stock": stock}

# ======================================================
# GLOBAL CONFIG (THEME & PLATFORM SETTINGS)
# ======================================================

@router.get(
    "/config/theme",
    summary="Get global theme configuration",
)
async def get_theme_config(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_config("theme")

@router.patch(
    "/config/theme",
    summary="Update global theme configuration",
)
async def update_theme_config(
    payload: dict,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.set_config("theme", payload)

@router.get(
    "/config/platform",
    summary="Get global platform settings",
)
async def get_platform_config(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_config("platform_settings")

@router.patch(
    "/config/platform",
    summary="Update global platform settings",
)
async def update_platform_config(
    payload: dict,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.set_config("platform_settings", payload)

# ======================================================
# ORDERS (admin — all orders site-wide)
# ======================================================

from datetime import date as date_type

@router.get(
    "/orders",
    response_model=AdminOrderListResponse,
    summary="Get all orders with pagination, search, filters & sorting (admin only)",
)
async def get_all_orders(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    search: Optional[str] = Query(None, description="Search term for order ID or shipping address"),
    status: Optional[str] = Query(None, description="Fulfillment status filter (Processing, Confirmed, Shipped, Out_For_Delivery, Delivered, Cancelled)"),
    payment_status: Optional[str] = Query(None, description="Payment status filter (PENDING, PAID, FAILED, REFUNDED)"),
    date_from: Optional[date_type] = Query(None, description="Filter orders created on or after date (YYYY-MM-DD)"),
    date_to: Optional[date_type] = Query(None, description="Filter orders created on or before date (YYYY-MM-DD)"),
    sort_by: str = Query("created_at", description="Field to sort by (created_at, total, status, payment_status)"),
    sort_order: str = Query("desc", description="Sort direction (asc, desc)"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.admin_list_orders(
        status=status,
        payment_status=payment_status,
        search=search,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        limit=limit,
    )


@router.get(
    "/orders/{order_id}",
    response_model=OrderResponse,
    summary="Get single order details (admin only)",
)
async def get_order_by_id(
    order_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    order = await service.admin_get_order(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' not found.")
    return order


@router.patch(
    "/orders/{order_id}/fulfillment-status",
    response_model=OrderResponse,
    summary="Update order fulfillment status (admin only)",
)
async def update_fulfillment_status(
    order_id: str,
    payload: FulfillmentStatusPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    try:
        return await service.admin_update_fulfillment_status(
            order_id=order_id,
            payload=payload,
            admin_id=current_user.id,
            admin_email=current_user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/orders/{order_id}/payment-status",
    response_model=OrderResponse,
    summary="Update order payment status (admin only)",
)
async def update_payment_status(
    order_id: str,
    payload: PaymentStatusPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    try:
        return await service.admin_update_payment_status(
            order_id=order_id,
            payload=payload,
            admin_id=current_user.id,
            admin_email=current_user.email,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/orders/{order_id}/invoice",
    summary="Get order invoice HTML or S3 redirect (admin only)",
)
async def get_admin_order_invoice(
    order_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import HTMLResponse, RedirectResponse
    from app.services.invoice_service import InvoiceService
    from app.repositories.order_repository import OrderRepository

    order_repo = OrderRepository(db)
    order = await order_repo.get_by_id(order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' not found.")

    user_name = "Customer"
    user_email = ""
    if order.user:
        user_name = order.user.full_name or "Customer"
        user_email = order.user.email or ""

    if getattr(order, "invoice_url", None) and str(order.invoice_url).startswith("http"):
        return RedirectResponse(url=order.invoice_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    cloud_url = await InvoiceService.generate_and_upload_invoice(order, user_name, user_email)
    if cloud_url:
        order.invoice_url = cloud_url
        await db.commit()
        return RedirectResponse(url=cloud_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    html = InvoiceService.generate_html_invoice(order, user_name, user_email)
    return HTMLResponse(content=html)


@router.patch(
    "/orders/{order_id}/status",
    response_model=OrderResponse,
    summary="Legacy update order status combined (admin only)",
)
async def legacy_update_order_status(
    order_id: str,
    payload: UpdateOrderStatusPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    try:
        order = await service.update_order_status(order_id, payload, admin_id=current_user.id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
        return order
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ======================================================
# USERS (admin)
# ======================================================

@router.get(
    "/users",
    response_model=list[SystemUserResponse],
    summary="Get all registered users (admin only)",
)
async def get_all_users(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_all_users()


@router.get(
    "/customers",
    response_model=CustomerListPaginatedResponse,
    summary="Get all customers with pagination, search, status filter & summary stats (admin only)",
)
async def get_customers(
    search: Optional[str] = Query(None, description="Search by name, email, or phone"),
    status: Optional[str] = Query(None, description="Filter by status: 'ALL', 'ACTIVE', 'INACTIVE'"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_customers_paginated(
        search=search,
        status=status,
        page=page,
        limit=limit,
    )


@router.get(
    "/customers/{user_id}",
    response_model=CustomerDetailsResponse,
    summary="Get customer details",
)
async def get_customer_details(
    user_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        return await service.get_customer_details(user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch(
    "/customers/{user_id}",
    response_model=CustomerDetailsResponse,
    summary="Update customer profile details (admin only)",
)
async def update_customer(
    user_id: str,
    payload: CustomerUpdatePayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        return await service.update_customer(user_id, payload, admin_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/customers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete customer account (admin only)",
)
async def delete_customer(
    user_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        await service.delete_customer(user_id, admin_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/users",
    response_model=SystemUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new administrator user (superadmin only)",
)
async def create_admin(
    payload: CreateAdminRequest,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        return await service.create_admin(payload, superadmin_id=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete/Revoke a user (superadmin only)",
)
async def delete_user(
    user_id: str,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.delete_user(user_id, superadmin_id=current_user.id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return None


@router.patch(
    "/users/{user_id}",
    response_model=SystemUserResponse,
    summary="Update an administrator's details (superadmin only)",
)
async def update_admin(
    user_id: str,
    payload: UpdateAdminRequest,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        updated = await service.update_admin(user_id, payload, superadmin_id=current_user.id)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Administrator user not found.")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post(
    "/users/{user_id}/promote",
    response_model=SystemUserResponse,
    summary="Promote an administrator to superadmin (superadmin only)",
)
async def promote_admin(
    user_id: str,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    updated = await service.promote_admin(user_id, superadmin_id=current_user.id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Administrator user not found or is already a superadmin.")
    return updated


@router.post(
    "/users/{user_id}/demote",
    response_model=SystemUserResponse,
    summary="Demote a superadmin to admin (superadmin only)",
)
async def demote_admin(
    user_id: str,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    try:
        updated = await service.demote_admin(user_id, superadmin_id=current_user.id)
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Superadmin user not found or is already an admin.")
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.patch(
    "/users/{user_id}/password",
    summary="Update an administrator password (superadmin only)",
)
async def update_admin_password(
    user_id: str,
    payload: UpdateAdminPasswordPayload,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.update_admin_password(user_id, payload.password, superadmin_id=current_user.id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Administrator user not found.")
    return {"message": "Administrator password updated successfully."}


# ======================================================
# SUPPORT TICKETS (admin — all tickets site-wide)
# ======================================================

@router.get(
    "/tickets",
    response_model=list[SupportTicketResponse],
    summary="Get all support tickets site-wide (admin only)",
)
async def get_all_tickets(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_all_tickets()


@router.post(
    "/tickets/{ticket_id}/status",
    response_model=SupportTicketResponse,
    summary="Update support ticket status (admin only)",
)
async def update_ticket_status(
    ticket_id: str,
    payload: UpdateTicketStatusPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    ticket = await service.update_ticket_status(ticket_id, payload, admin_id=current_user.id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return ticket

@router.put(
    "/tickets/{ticket_id}/resolve",
    response_model=SupportTicketResponse,
    summary="Resolve a support ticket (admin only)",
)
async def resolve_ticket(
    ticket_id: str,
    payload: ResolveTicketPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    ticket = await service.resolve_ticket(ticket_id, payload, admin_id=current_user.id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


# ======================================================
# OFFLINE SALES
# ======================================================

@router.get(
    "/offline-sales",
    response_model=list[OfflineSaleResponse],
    summary="Get all offline (POS) sales records (admin only)",
)
async def get_offline_sales(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_offline_sales()


@router.post(
    "/offline-sales",
    response_model=OfflineSaleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log an offline company/b2b sale (admin only)",
)
async def add_offline_sale(
    payload: OfflineSalePayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = AdminService(db)
        return await service.add_offline_sale(payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/offline-sales/import",
    response_model=ImportSalesResponse,
    summary="Bulk import offline sales from a CSV file (admin only)",
)
async def import_offline_sales(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    service = AdminService(db)
    return await service.import_offline_sales_csv(content)


# ======================================================
# BANNER IMAGE UPLOAD (superadmin)
# ======================================================

@router.post(
    "/banners/{banner_id}/image",
    response_model=BannerImageResponse,
    summary="Upload a banner hero image (superadmin only)",
)
async def upload_banner_image(
    banner_id: str,
    image: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    image_url = await service.upload_banner_image(banner_id, image_file=image)
    return BannerImageResponse(image_url=image_url)


# ======================================================
# CMS — BANNERS
# ======================================================

@router.post(
    "/banners",
    response_model=BannerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new banner (admin only)",
)
async def create_banner(
    title: str = Form(...),
    subtitle: str = Form(...),
    tag: str = Form(...),
    button_text: str = Form(...),
    link: str = Form(...),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    image: UploadFile = File(default=None),
    image_url: Optional[str] = Form(default=None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    payload = CreateBannerRequest(
        title=title,
        subtitle=subtitle,
        tag=tag,
        image=image_url,
        button_text=button_text,
        link=link,
        sort_order=sort_order,
        is_active=is_active,
    )
    service = AdminService(db)
    return await service.create_banner(payload, image_file=image)


@router.patch(
    "/banners/{banner_id}",
    response_model=BannerResponse,
    summary="Update a banner (admin only)",
)
async def update_banner(
    banner_id: str,
    payload: UpdateBannerRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.update_banner(banner_id, payload)

@router.delete(
    "/banners/{banner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a banner (superadmin only)",
)
async def delete_banner(
    banner_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.delete_banner(banner_id, superadmin_id=current_user.id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Banner not found.")
    return None


# ======================================================
# CMS — TESTIMONIALS
# ======================================================

@router.get(
    "/testimonials",
    summary="Get all testimonials for moderation (admin only)",
)
async def admin_get_testimonials(
    status: Optional[str] = Query(default=None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_all_testimonials(status=status)


@router.post(
    "/testimonials",
    response_model=TestimonialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer testimonial (admin only)",
)
async def create_testimonial(
    author: str = Form(...),
    title: str = Form(default="Chocolate Enthusiast"),
    text: str = Form(...),
    rating: float = Form(default=5.0),
    initials: Optional[str] = Form(default=None),
    avatar_url: Optional[str] = Form(default=None),
    avatar: UploadFile = File(default=None),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    payload = CreateTestimonialRequest(
        author=author,
        title=title,
        text=text,
        rating=rating,
        initials=initials or author[:2].upper(),
        avatar_url=avatar_url,
        sort_order=sort_order,
        is_active=is_active,
    )
    service = AdminService(db)
    return await service.create_testimonial(payload, avatar_file=avatar)


class UpdateTestimonialStatusPayload(BaseModel):
    status: str  # approved, rejected, pending


@router.patch(
    "/testimonials/{testimonial_id}/status",
    summary="Approve, reject, or update testimonial status (admin only)",
)
async def update_testimonial_status(
    testimonial_id: str,
    payload: UpdateTestimonialStatusPayload,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    updated = await service.update_testimonial_status(testimonial_id, payload.status)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testimonial not found.")
    return updated


@router.delete(
    "/testimonials/{testimonial_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer testimonial (admin only)",
)
async def delete_testimonial(
    testimonial_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.delete_testimonial(testimonial_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testimonial not found.")
    return None


# ======================================================
# PRODUCT REVIEWS MODERATION (Admin)
# ======================================================

@router.get(
    "/reviews",
    summary="Get all product reviews site-wide (admin only)",
)
async def admin_get_all_reviews(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_all_reviews()


@router.delete(
    "/reviews/{review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a product review and recalculate product rating (admin only)",
)
async def admin_delete_review(
    review_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    deleted = await service.delete_review(review_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found.")
    return None


# ======================================================
# CMS — INSTAGRAM REELS
# ======================================================

@router.post(
    "/reels",
    response_model=ReelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Instagram reel entry (admin only)",
)
async def create_reel(
    title: str = Form(...),
    likes: str = Form(default="0"),
    comments: str = Form(default="0"),
    views: str = Form(default="0 views"),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    video_url: Optional[str] = Form(default=None),
    video: UploadFile = File(default=None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    payload = CreateReelRequest(
        video_url=video_url,
        likes=likes,
        comments=comments,
        views=views,
        title=title,
        sort_order=sort_order,
        is_active=is_active,
    )
    service = AdminService(db)
    return await service.create_reel(payload, video_file=video)


@router.delete(
    "/reels/{reel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an Instagram reel (admin only)",
)
async def delete_reel(
    reel_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.delete_reel(reel_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reel not found.")
    return None


@router.patch(
    "/reels/{reel_id}",
    response_model=ReelResponse,
    summary="Update an Instagram reel (admin only)",
)
async def update_reel(
    reel_id: str,
    title: Optional[str] = Form(default=None),
    likes: Optional[str] = Form(default=None),
    comments: Optional[str] = Form(default=None),
    views: Optional[str] = Form(default=None),
    video_url: Optional[str] = Form(default=None),
    video: UploadFile = File(default=None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    try:
        return await service.update_reel(
            reel_id,
            title=title,
            likes=likes,
            comments=comments,
            views=views,
            video_url=video_url,
            video_file=video if (video and video.filename) else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ======================================================
# CMS — TESTIMONIALS
# ======================================================

@router.post(
    "/testimonials",
    response_model=TestimonialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer testimonial (admin only)",
)
async def create_testimonial(
    author: str = Form(...),
    title: str = Form(...),
    text: str = Form(...),
    rating: float = Form(default=5.0),
    initials: Optional[str] = Form(default=None),
    avatar_url: Optional[str] = Form(default=None),
    avatar: UploadFile = File(default=None),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    payload = CreateTestimonialRequest(
        author=author,
        title=title,
        text=text,
        rating=rating,
        initials=initials or author[:2].upper(),
        avatar_url=avatar_url,
        sort_order=sort_order,
        is_active=is_active,
    )
    service = AdminService(db)
    return await service.create_testimonial(payload, avatar_file=avatar)


@router.delete(
    "/testimonials/{testimonial_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a customer testimonial (admin only)",
)
async def delete_testimonial(
    testimonial_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    success = await service.delete_testimonial(testimonial_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testimonial not found.")
    return None


# ======================================================
# CMS — SITE CONFIG (STATS / CONTACT)
# ======================================================

@router.put(
    "/config/stats",
    response_model=StatsResponse,
    summary="Set home page site stats (admin only)",
)
@router.patch(
    "/config/stats",
    response_model=StatsResponse,
    summary="Set home page site stats (admin only)",
)
async def set_stats(
    payload: SetStatsRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.set_stats(payload)


@router.put(
    "/config/contact",
    response_model=ContactInfoResponse,
    summary="Set home page contact info (admin only)",
)
@router.patch(
    "/config/contact",
    response_model=ContactInfoResponse,
    summary="Set home page contact info (admin only)",
)
async def set_contact(
    payload: SetContactRequest,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.set_contact(payload)


# ======================================================
# CONTACT FORM MESSAGES (admin view)
# ======================================================

@router.get(
    "/contact-messages",
    summary="Get all submitted contact messages (admin only)",
)
async def get_contact_messages(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    return await service.get_contact_messages()


@router.delete(
    "/contact-messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a contact message (admin only)",
)
async def delete_contact_message(
    message_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    deleted = await service.delete_contact_message(message_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    return None


# ======================================================
# OUR STORY CRAFTING VIDEO UPLOAD
# ======================================================

@router.post(
    "/story-video",
    summary="Upload Our Story crafting video (admin only)",
)
async def upload_story_video(
    video: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    video_url = await service.upload_story_video(video)
    return {"video_url": video_url}


@router.delete(
    "/story-video",
    summary="Delete / reset Our Story crafting video (admin only)",
)
async def delete_story_video(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    video_url = await service.delete_story_video()
    return {"video_url": video_url}


# ======================================================
# CATEGORIES (Admin Management)
# ======================================================

@router.get(
    "/categories",
    response_model=list[AdminCategoryResponse],
    summary="List all categories including inactive (admin only)",
)
async def admin_get_all_categories(
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    categories = await service.admin_get_all_categories()
    return [AdminCategoryResponse.model_validate(c) for c in categories]


@router.post(
    "/categories",
    response_model=AdminCategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new category with optional image upload (admin only)",
)
async def admin_create_category(
    name: str = Form(...),
    slug: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    sort_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    image_url: Optional[str] = Form(default=None),
    image: Optional[UploadFile] = File(default=None),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    import re
    final_slug = slug or re.sub(r"[^\w\s-]", "", name.lower().strip()).replace(" ", "-")
    category = await service.admin_create_category(
        name=name,
        slug=final_slug,
        description=description,
        sort_order=sort_order,
        is_active=is_active,
        image_file=image if (image and image.filename) else None,
        image_url=image_url,
    )
    return AdminCategoryResponse.model_validate(category)


@router.patch(
    "/categories/{category_id}",
    response_model=AdminCategoryResponse,
    summary="Update a category (admin only)",
)
async def admin_update_category(
    category_id: str,
    payload: CategoryUpdate,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    update_dict = payload.model_dump(exclude_unset=True)
    category = await service.admin_update_category(category_id, **update_dict)
    if not category:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return AdminCategoryResponse.model_validate(category)


@router.delete(
    "/categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a category (admin only)",
)
async def admin_delete_category(
    category_id: str,
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    deleted = await service.admin_delete_category(category_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")


@router.post(
    "/categories/{category_id}/image",
    summary="Upload or replace category image (admin only)",
)
async def admin_upload_category_image(
    category_id: str,
    image: UploadFile = File(...),
    current_user: User = Depends(require_role("admin", "superadmin")),
    db: AsyncSession = Depends(get_db),
):
    service = AdminService(db)
    new_url = await service.admin_upload_category_image(category_id, image)
    if not new_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return {"image_url": new_url}
