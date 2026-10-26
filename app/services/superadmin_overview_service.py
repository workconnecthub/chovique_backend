import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.offline_sale import OfflineSale
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User
from app.schemas.superadmin_overview import (
    KPICardData,
    RecentActivityItem,
    RevenueTrendPoint,
    SalesSourceData,
    SuperadminOverviewResponse,
    TopSellingProductOverview,
    PaymentMetrics,
)

logger = logging.getLogger(__name__)

VALID_PAID_STATUSES = ["Paid", "Delivered", "Shipped", "Processing", "Confirmed", "Completed", "Out_For_Delivery"]


def calculate_pct_change(current: float, previous: float) -> float:
    if previous > 0:
        return round(((current - previous) / previous) * 100.0, 1)
    if current > 0:
        return 100.0
    return 0.0


def resolve_superadmin_date_ranges(
    timeframe: str = "7days",
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> Tuple[datetime, datetime, datetime, datetime, str]:
    now = datetime.now(timezone.utc)

    if start_date and end_date:
        curr_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        curr_end = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        delta = curr_end - curr_start
        prev_end = curr_start - timedelta(seconds=1)
        prev_start = prev_end - delta
        label = "vs previous period"
        return curr_start, curr_end, prev_start, prev_end, label

    tf = (timeframe or "7days").lower()

    if tf == "today":
        curr_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=timezone.utc)
        curr_end = now
        prev_start = curr_start - timedelta(days=1)
        prev_end = datetime.combine(prev_start.date(), datetime.max.time(), tzinfo=timezone.utc)
        label = "vs yesterday"
    elif tf == "30days":
        curr_start = now - timedelta(days=29)
        curr_end = now
        prev_start = curr_start - timedelta(days=30)
        prev_end = curr_start - timedelta(seconds=1)
        label = "vs last 30 days"
    elif tf == "3months":
        curr_start = now - timedelta(days=89)
        curr_end = now
        prev_start = curr_start - timedelta(days=90)
        prev_end = curr_start - timedelta(seconds=1)
        label = "vs last 3 months"
    elif tf == "1year":
        curr_start = now - timedelta(days=364)
        curr_end = now
        prev_start = curr_start - timedelta(days=365)
        prev_end = curr_start - timedelta(seconds=1)
        label = "vs last 1 year"
    else:  # default "7days"
        curr_start = now - timedelta(days=6)
        curr_end = now
        prev_start = curr_start - timedelta(days=7)
        prev_end = curr_start - timedelta(seconds=1)
        label = "vs last 7 days"

    return curr_start, curr_end, prev_start, prev_end, label


class SuperadminOverviewService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_overview(
        self,
        timeframe: str = "7days",
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> SuperadminOverviewResponse:
        curr_start, curr_end, prev_start, prev_end, label = resolve_superadmin_date_ranges(
            timeframe, start_date, end_date
        )

        # -----------------------------------------------------
        # 1. Total Revenue (Current vs Previous)
        # -----------------------------------------------------
        curr_online_res = await self.db.execute(
            select(func.coalesce(func.sum(Order.total), 0.0)).where(
                func.upper(Order.payment_status) == "PAID",
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        curr_online_rev = float(curr_online_res.scalar() or 0.0)

        curr_offline_res = await self.db.execute(
            select(func.coalesce(func.sum(OfflineSale.total_price), 0.0)).where(
                OfflineSale.created_at >= curr_start,
                OfflineSale.created_at <= curr_end,
            )
        )
        curr_offline_rev = float(curr_offline_res.scalar() or 0.0)
        curr_total_revenue = round(curr_online_rev + curr_offline_rev, 2)

        prev_online_res = await self.db.execute(
            select(func.coalesce(func.sum(Order.total), 0.0)).where(
                func.upper(Order.payment_status) == "PAID",
                Order.created_at >= prev_start,
                Order.created_at <= prev_end,
            )
        )
        prev_online_rev = float(prev_online_res.scalar() or 0.0)

        prev_offline_res = await self.db.execute(
            select(func.coalesce(func.sum(OfflineSale.total_price), 0.0)).where(
                OfflineSale.created_at >= prev_start,
                OfflineSale.created_at <= prev_end,
            )
        )
        prev_offline_rev = float(prev_offline_res.scalar() or 0.0)
        prev_total_revenue = round(prev_online_rev + prev_offline_rev, 2)

        rev_pct_change = calculate_pct_change(curr_total_revenue, prev_total_revenue)

        # -----------------------------------------------------
        # 2. Total Orders & Online / Offline breakdown (Current vs Previous)
        # -----------------------------------------------------
        curr_orders_res = await self.db.execute(
            select(func.count(Order.id)).where(
                Order.status.in_(VALID_PAID_STATUSES),
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        curr_orders = int(curr_orders_res.scalar() or 0)
        curr_online_orders = curr_orders

        prev_orders_res = await self.db.execute(
            select(func.count(Order.id)).where(
                Order.status.in_(VALID_PAID_STATUSES),
                Order.created_at >= prev_start,
                Order.created_at <= prev_end,
            )
        )
        prev_orders = int(prev_orders_res.scalar() or 0)
        prev_online_orders = prev_orders

        curr_offline_orders_res = await self.db.execute(
            select(func.count(OfflineSale.id)).where(
                OfflineSale.created_at >= curr_start,
                OfflineSale.created_at <= curr_end,
            )
        )
        curr_offline_orders = int(curr_offline_orders_res.scalar() or 0)

        prev_offline_orders_res = await self.db.execute(
            select(func.count(OfflineSale.id)).where(
                OfflineSale.created_at >= prev_start,
                OfflineSale.created_at <= prev_end,
            )
        )
        prev_offline_orders = int(prev_offline_orders_res.scalar() or 0)

        orders_pct_change = calculate_pct_change(float(curr_orders), float(prev_orders))
        online_orders_pct_change = calculate_pct_change(float(curr_online_orders), float(prev_online_orders))
        offline_orders_pct_change = calculate_pct_change(float(curr_offline_orders), float(prev_offline_orders))

        # -----------------------------------------------------
        # 3. Total Customers (Registered customers count)
        # -----------------------------------------------------
        curr_cust_res = await self.db.execute(
            select(func.count(User.id)).where(
                User.role == "customer",
                User.created_at <= curr_end,
            )
        )
        curr_cust = int(curr_cust_res.scalar() or 0)

        prev_cust_res = await self.db.execute(
            select(func.count(User.id)).where(
                User.role == "customer",
                User.created_at <= prev_end,
            )
        )
        prev_cust = int(prev_cust_res.scalar() or 0)

        cust_pct_change = calculate_pct_change(float(curr_cust), float(prev_cust))

        # -----------------------------------------------------
        # 4. Active Admins
        # -----------------------------------------------------
        curr_admin_res = await self.db.execute(
            select(func.count(User.id)).where(
                User.role.in_(["admin", "superadmin", "super_admin"]),
                User.is_active == True,
            )
        )
        active_admins_count = int(curr_admin_res.scalar() or 0)

        prev_admin_res = await self.db.execute(
            select(func.count(User.id)).where(
                User.role.in_(["admin", "superadmin", "super_admin"]),
                User.is_active == True,
                User.created_at <= prev_end,
            )
        )
        prev_admins_count = int(prev_admin_res.scalar() or 0)
        admin_pct_change = calculate_pct_change(float(active_admins_count), float(prev_admins_count))

        # -----------------------------------------------------
        # 5. Revenue Trend Data
        # -----------------------------------------------------
        # Fetch all online orders & offline sales in timeframe
        orders_list_res = await self.db.execute(
            select(Order.total, Order.created_at).where(
                Order.status.in_(VALID_PAID_STATUSES),
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        online_orders = orders_list_res.all()

        offline_sales_res = await self.db.execute(
            select(OfflineSale.total_price, OfflineSale.created_at).where(
                OfflineSale.created_at >= curr_start,
                OfflineSale.created_at <= curr_end,
            )
        )
        offline_sales = offline_sales_res.all()

        # Build daily or step trend points
        trend_map = {}

        # Pre-populate dates
        step_days = max(1, (curr_end.date() - curr_start.date()).days)
        # Determine number of points (limit between 5 and 31 for clean chart)
        num_buckets = min(step_days + 1, 14) if step_days <= 14 else 12
        bucket_size_days = max(1, step_days // num_buckets)

        cur_date = curr_start.date()
        while cur_date <= curr_end.date():
            d_str = cur_date.strftime("%d %b")
            trend_map[d_str] = 0.0
            cur_date += timedelta(days=bucket_size_days)

        for total, dt in online_orders:
            if dt:
                d_str = dt.strftime("%d %b")
                # find closest bucket or add
                if d_str in trend_map:
                    trend_map[d_str] += float(total or 0.0)
                else:
                    trend_map[d_str] = float(total or 0.0)

        for total, dt in offline_sales:
            if dt:
                d_str = dt.strftime("%d %b")
                if d_str in trend_map:
                    trend_map[d_str] += float(total or 0.0)
                else:
                    trend_map[d_str] = float(total or 0.0)

        revenue_trend = [
            RevenueTrendPoint(date=k, revenue=round(v, 2))
            for k, v in trend_map.items()
        ]

        # -----------------------------------------------------
        # 6. Sales Source Distribution
        # -----------------------------------------------------
        total_sales_combined = curr_online_rev + curr_offline_rev
        if total_sales_combined > 0:
            online_pct = round((curr_online_rev / total_sales_combined) * 100.0, 1)
            offline_pct = round((curr_offline_rev / total_sales_combined) * 100.0, 1)
        else:
            online_pct = 0.0
            offline_pct = 0.0

        sales_source = SalesSourceData(
            online_revenue=curr_online_rev,
            online_percentage=online_pct,
            offline_revenue=curr_offline_rev,
            offline_percentage=offline_pct,
        )

        # -----------------------------------------------------
        # 7. Top Selling Products
        # -----------------------------------------------------
        top_products_q = (
            select(
                Product.id,
                Product.name,
                Product.image,
                func.sum(OrderItem.quantity).label("units_sold"),
                func.sum(OrderItem.price * OrderItem.quantity).label("total_revenue"),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.status.in_(VALID_PAID_STATUSES),
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
            .group_by(Product.id, Product.name, Product.image)
            .order_by(desc("units_sold"), desc("total_revenue"))
            .limit(5)
        )
        top_prod_res = await self.db.execute(top_products_q)
        top_prod_rows = top_prod_res.all()

        top_selling_products = []
        for row in top_prod_rows:
            top_selling_products.append(
                TopSellingProductOverview(
                    id=row.id,
                    name=row.name,
                    image_url=row.image,
                    units_sold=int(row.units_sold or 0),
                    revenue=round(float(row.total_revenue or 0.0), 2),
                )
            )



        # -----------------------------------------------------
        # 8. Recent Activity Logs
        # -----------------------------------------------------
        activities_q = (
            select(AuditLog, User.full_name)
            .outerjoin(User, User.id == AuditLog.user_id)
            .order_by(desc(AuditLog.created_at))
            .limit(6)
        )
        act_res = await self.db.execute(activities_q)
        act_rows = act_res.all()

        recent_activities = []
        for log_entry, user_name in act_rows:
            ts_str = log_entry.created_at.strftime("%d %b %Y, %I:%M %p") if log_entry.created_at else ""
            desc_val = log_entry.details or (f"{log_entry.action} in {log_entry.module}" if log_entry.module else log_entry.action)
            recent_activities.append(
                RecentActivityItem(
                    id=log_entry.id,
                    action=log_entry.action,
                    description=desc_val,
                    timestamp=ts_str,
                    user_name=user_name or "System",
                )
            )

        # Payment Metrics
        pm_completed_res = await self.db.execute(
            select(func.count(Order.id)).where(
                func.upper(Order.payment_status) == "PAID",
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        pm_completed = pm_completed_res.scalar() or 0

        pm_pending_res = await self.db.execute(
            select(func.count(Order.id)).where(
                func.upper(Order.payment_status).in_(["PENDING", "PROCESSING"]),
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        pm_pending = pm_pending_res.scalar() or 0

        pm_cancelled_res = await self.db.execute(
            select(func.count(Order.id)).where(
                func.upper(Order.payment_status).in_(["FAILED", "CANCELLED", "REFUNDED", "REFUND PENDING", "PARTIALLY REFUNDED"]),
                Order.created_at >= curr_start,
                Order.created_at <= curr_end,
            )
        )
        pm_cancelled = pm_cancelled_res.scalar() or 0

        payment_metrics = PaymentMetrics(
            completed=pm_completed,
            pending=pm_pending,
            cancelled=pm_cancelled,
        )

        return SuperadminOverviewResponse(
            total_revenue=KPICardData(
                current_value=curr_total_revenue,
                previous_value=prev_total_revenue,
                percentage_change=rev_pct_change,
                comparison_label=label,
            ),
            total_orders=KPICardData(
                current_value=float(curr_orders),
                previous_value=float(prev_orders),
                percentage_change=orders_pct_change,
                comparison_label=label,
            ),
            online_orders=KPICardData(
                current_value=float(curr_online_orders),
                previous_value=float(prev_online_orders),
                percentage_change=online_orders_pct_change,
                comparison_label=label,
            ),
            offline_orders=KPICardData(
                current_value=float(curr_offline_orders),
                previous_value=float(prev_offline_orders),
                percentage_change=offline_orders_pct_change,
                comparison_label=label,
            ),
            total_customers=KPICardData(
                current_value=float(curr_cust),
                previous_value=float(prev_cust),
                percentage_change=cust_pct_change,
                comparison_label=label,
            ),
            active_admins=KPICardData(
                current_value=float(active_admins_count),
                previous_value=float(prev_admins_count),
                percentage_change=admin_pct_change,
                comparison_label=label,
            ),
            payment_metrics=payment_metrics,
            revenue_trend=revenue_trend,
            sales_source=sales_source,
            top_selling_products=top_selling_products,
            recent_activities=recent_activities,
        )
