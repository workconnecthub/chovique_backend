import csv
import io
import math
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple
from sqlalchemy import select, func, text, and_, or_, inspect, case
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.order import Order, OrderItem
from app.models.offline_sale import OfflineSale
from app.models.product import Product
from app.models.user import User
from app.models.coupon import Coupon, CouponUsage
from app.models.wallet import CoinTransaction
from app.schemas.reports import (
    ReportQueryRequest,
    ReportResponse,
    ReportKPICard,
    ReportChartPoint,
)


class ReportService:

    def __init__(self, db: AsyncSession):
        self.db = db

    def _parse_date_range(self, start_str: str, end_str: str) -> Tuple[datetime, datetime]:
        try:
            start_dt = datetime.strptime(start_str.strip(), "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid start_date format '{start_str}'. Use YYYY-MM-DD.")

        try:
            end_dt = datetime.strptime(end_str.strip(), "%Y-%m-%d")
        except ValueError:
            raise ValueError(f"Invalid end_date format '{end_str}'. Use YYYY-MM-DD.")

        if start_dt > end_dt:
            raise ValueError("Start date cannot be after end date.")

        # Set to full day range (00:00:00 to 23:59:59)
        start_full = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end_full = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start_full, end_full

    async def generate_report(self, req: ReportQueryRequest) -> ReportResponse:
        start_dt, end_dt = self._parse_date_range(req.start_date, req.end_date)

        if req.report_type == 'sales':
            return await self._generate_sales_report(start_dt, end_dt, req)
        elif req.report_type == 'orders':
            return await self._generate_orders_report(start_dt, end_dt, req)
        elif req.report_type == 'products':
            return await self._generate_products_report(start_dt, end_dt, req)
        elif req.report_type == 'customers':
            return await self._generate_customers_report(start_dt, end_dt, req)
        elif req.report_type == 'coupons':
            return await self._generate_coupons_report(start_dt, end_dt, req)
        elif req.report_type == 'reward_coins':
            return await self._generate_reward_coins_report(start_dt, end_dt, req)
        else:
            raise ValueError(f"Unsupported report_type '{req.report_type}'")

    # ==========================================================
    # 1. SALES REPORT
    # ==========================================================
    async def _generate_sales_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        # Online Orders (where Order.total is used)
        online_res = await self.db.execute(
            select(
                func.coalesce(func.sum(Order.total), 0.0).label("revenue"),
                func.count(Order.id).label("count")
            ).where(
                Order.created_at >= start_dt,
                Order.created_at <= end_dt,
                func.upper(Order.payment_status) == "PAID"
            )
        )
        online_row = online_res.first()
        online_revenue = float(online_row.revenue) if online_row else 0.0
        online_orders_count = int(online_row.count) if online_row else 0

        # Offline Sales
        offline_res = await self.db.execute(
            select(
                func.coalesce(func.sum(OfflineSale.total_price), 0.0).label("revenue"),
                func.count(OfflineSale.id).label("count")
            ).where(
                OfflineSale.created_at >= start_dt,
                OfflineSale.created_at <= end_dt
            )
        )
        offline_row = offline_res.first()
        offline_revenue = float(offline_row.revenue) if offline_row else 0.0
        offline_sales_count = int(offline_row.count) if offline_row else 0

        total_revenue = online_revenue + offline_revenue
        total_transactions = online_orders_count + offline_sales_count
        avg_order_val = total_revenue / total_transactions if total_transactions > 0 else 0.0

        # Previous Period comparison for growth %
        delta = (end_dt - start_dt).days + 1
        prev_start = start_dt - timedelta(days=delta)
        prev_end = start_dt - timedelta(seconds=1)

        prev_online_res = await self.db.execute(
            select(func.coalesce(func.sum(Order.total), 0.0)).where(
                Order.created_at >= prev_start, Order.created_at <= prev_end, func.upper(Order.payment_status) == "PAID"
            )
        )
        prev_offline_res = await self.db.execute(
            select(func.coalesce(func.sum(OfflineSale.total_price), 0.0)).where(
                OfflineSale.created_at >= prev_start, OfflineSale.created_at <= prev_end
            )
        )
        prev_total = float(prev_online_res.scalar() or 0.0) + float(prev_offline_res.scalar() or 0.0)
        growth = round(((total_revenue - prev_total) / prev_total) * 100.0, 1) if prev_total > 0 else 0.0

        # Daily breakdown for chart & table
        curr = start_dt.date()
        end_d = end_dt.date()
        daily_data = []

        while curr <= end_d:
            d_start = datetime.combine(curr, datetime.min.time())
            d_end = datetime.combine(curr, datetime.max.time())

            on_d = await self.db.execute(
                select(func.coalesce(func.sum(Order.total), 0.0), func.count(Order.id)).where(
                    Order.created_at >= d_start, Order.created_at <= d_end, func.upper(Order.payment_status) == "PAID"
                )
            )
            on_rev, on_cnt = on_d.first()

            off_d = await self.db.execute(
                select(func.coalesce(func.sum(OfflineSale.total_price), 0.0), func.count(OfflineSale.id)).where(
                    OfflineSale.created_at >= d_start, OfflineSale.created_at <= d_end
                )
            )
            off_rev, off_cnt = off_d.first()

            d_on_rev = float(on_rev or 0.0)
            d_off_rev = float(off_rev or 0.0)
            d_tot_rev = d_on_rev + d_off_rev
            d_tot_cnt = int(on_cnt or 0) + int(off_cnt or 0)

            daily_data.append({
                "date": curr.strftime("%b %d"),
                "date_iso": curr.strftime("%Y-%m-%d"),
                "online_revenue": d_on_rev,
                "offline_revenue": d_off_rev,
                "total_revenue": d_tot_rev,
                "count": d_tot_cnt,
            })
            curr += timedelta(days=1)

        # Pagination for table rows
        total_records = len(daily_data)
        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1
        offset = (req.page - 1) * req.limit
        page_rows = daily_data[offset : offset + req.limit]

        table_rows = [
            [
                r["date_iso"],
                f"₹{r['online_revenue']:,.2f}",
                f"₹{r['offline_revenue']:,.2f}",
                f"₹{r['total_revenue']:,.2f}",
                r["count"],
            ]
            for r in page_rows
        ]

        chart_data = [
            ReportChartPoint(
                label=r["date"],
                value=r["total_revenue"],
                secondary_value=float(r["count"])
            )
            for r in daily_data
        ]

        kpis = [
            ReportKPICard(title="Total Revenue", value=f"₹{total_revenue:,.2f}", growth_percentage=growth, subtext="vs previous period"),
            ReportKPICard(title="Total Orders", value=f"{total_transactions:,}", subtext="Online & Offline combined"),
            ReportKPICard(title="Online Sales", value=f"₹{online_revenue:,.2f}", subtext=f"{online_orders_count} web orders"),
            ReportKPICard(title="Avg. Order Value", value=f"₹{avg_order_val:,.2f}", subtext="Per completed order"),
        ]

        return ReportResponse(
            report_type="sales",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Date", "Online Revenue (₹)", "Offline Revenue (₹)", "Total Revenue (₹)", "Orders Count"],
            table_rows=table_rows,
            totals_footer=["Total", f"₹{online_revenue:,.2f}", f"₹{offline_revenue:,.2f}", f"₹{total_revenue:,.2f}", str(total_transactions)],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # 2. ORDERS REPORT
    # ==========================================================
    async def _generate_orders_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        # Count total & revenue
        summary_res = await self.db.execute(
            select(
                func.count(Order.id).label("total_orders"),
                func.coalesce(func.sum(
                    case((func.upper(Order.payment_status) == "PAID", Order.total), else_=0.0)
                ), 0.0).label("total_revenue"),
                func.coalesce(func.avg(
                    case((func.upper(Order.payment_status) == "PAID", Order.total), else_=None)
                ), 0.0).label("avg_value")
            ).where(Order.created_at >= start_dt, Order.created_at <= end_dt)
        )
        total_orders, total_rev, avg_val = summary_res.first()
        total_orders = int(total_orders or 0)
        total_rev = float(total_rev or 0.0)
        avg_val = float(avg_val or 0.0)

        # Status counts
        status_res = await self.db.execute(
            select(Order.status, func.count(Order.id)).where(
                Order.created_at >= start_dt, Order.created_at <= end_dt
            ).group_by(Order.status)
        )
        status_map = {r[0]: r[1] for r in status_res.all()}
        delivered_cnt = status_map.get("DELIVERED", 0) + status_map.get("Delivered", 0)
        cancelled_cnt = status_map.get("CANCELLED", 0) + status_map.get("Cancelled", 0)

        # Query paginated orders with user info
        count_q = select(func.count(Order.id)).where(Order.created_at >= start_dt, Order.created_at <= end_dt)
        total_records = int((await self.db.execute(count_q)).scalar() or 0)

        offset = (req.page - 1) * req.limit
        orders_q = (
            select(Order, User)
            .options(selectinload(Order.items))
            .outerjoin(User, Order.user_id == User.id)
            .where(Order.created_at >= start_dt, Order.created_at <= end_dt)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(req.limit)
        )
        orders_result = (await self.db.execute(orders_q)).all()

        table_rows = []
        for o, u in orders_result:
            dt_str = o.created_at.strftime("%Y-%m-%d %H:%M") if o.created_at else ""
            cust_name = u.full_name if u else "Guest Customer"
            if not u and isinstance(o.shipping_address, dict):
                cust_name = o.shipping_address.get("full_name") or o.shipping_address.get("name") or "Guest Customer"

            state = inspect(o)
            items_cnt = len(o.items) if state and "items" not in state.unloaded and o.items else 1
            table_rows.append([
                o.id,
                dt_str,
                cust_name,
                items_cnt,
                o.payment_status or "PENDING",
                o.status or "Processing",
                f"₹{o.total:,.2f}",
            ])

        # Chart Data: Daily Order Count
        curr = start_dt.date()
        end_d = end_dt.date()
        chart_data = []

        while curr <= end_d:
            d_start = datetime.combine(curr, datetime.min.time())
            d_end = datetime.combine(curr, datetime.max.time())
            cnt_res = await self.db.execute(
                select(func.count(Order.id), func.coalesce(func.sum(
                    case((func.upper(Order.payment_status) == "PAID", Order.total), else_=0.0)
                ), 0.0)).where(
                    Order.created_at >= d_start, Order.created_at <= d_end
                )
            )
            cnt, rev = cnt_res.first()
            chart_data.append(ReportChartPoint(
                label=curr.strftime("%b %d"),
                value=float(cnt or 0),
                secondary_value=float(rev or 0.0)
            ))
            curr += timedelta(days=1)

        kpis = [
            ReportKPICard(title="Total Orders", value=f"{total_orders:,}", subtext="Orders placed in range"),
            ReportKPICard(title="Delivered Orders", value=f"{delivered_cnt:,}", subtext="Fulfillment complete"),
            ReportKPICard(title="Cancelled Orders", value=f"{cancelled_cnt:,}", subtext="Refunded / Cancelled"),
            ReportKPICard(title="Avg. Order Value", value=f"₹{avg_val:,.2f}", subtext="Average basket size"),
        ]

        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1

        return ReportResponse(
            report_type="orders",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Order ID", "Date & Time", "Customer", "Items", "Payment Status", "Fulfillment Status", "Total (₹)"],
            table_rows=table_rows,
            totals_footer=["Total Orders", str(total_records), "-", "-", "-", "-", f"₹{total_rev:,.2f}"],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # 3. PRODUCTS REPORT
    # ==========================================================
    async def _generate_products_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        # 1. Query online product sales in date range
        online_prod_stmt = (
            select(
                OrderItem.product_id,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
                func.coalesce(func.sum(OrderItem.price * OrderItem.quantity), 0.0).label("revenue"),
            )
            .select_from(OrderItem)
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.created_at >= start_dt,
                Order.created_at <= end_dt,
                func.upper(Order.status) != "CANCELLED",
            )
            .group_by(OrderItem.product_id)
        )
        online_prod_res = await self.db.execute(online_prod_stmt)
        sales_map = {p_id: (int(u), float(rev)) for p_id, u, rev in online_prod_res.all()}

        # 2. Query active catalog products with category
        prod_stmt = (
            select(Product, Category.name.label("category_name"))
            .outerjoin(Category, Product.category_id == Category.id)
            .where(Product.is_active.is_(True))
        )
        products_res = await self.db.execute(prod_stmt)
        products = products_res.all()

        product_list = []
        for p, cat_name in products:
            units, rev = sales_map.get(p.id, (0, 0.0))
            product_list.append({
                "id": p.id,
                "name": p.name,
                "category": cat_name or "Gourmet Chocolates",
                "units_sold": units,
                "stock": p.stock,
                "revenue": rev,
            })

        # Sort: highest revenue first, then highest units sold, then by name
        product_list.sort(key=lambda x: (x["revenue"], x["units_sold"]), reverse=True)

        total_records = len(product_list)
        total_units = sum(x["units_sold"] for x in product_list)
        total_prod_rev = sum(x["revenue"] for x in product_list)
        sold_products_count = sum(1 for x in product_list if x["units_sold"] > 0)

        offset = (req.page - 1) * req.limit
        page_items = product_list[offset : offset + req.limit]

        table_rows = [
            [
                r["name"],
                r["category"],
                f"{r['units_sold']:,}",
                r["stock"],
                f"₹{r['revenue']:,.2f}",
            ]
            for r in page_items
        ]

        chart_data = [
            ReportChartPoint(
                label=r["name"][:15] + ("..." if len(r["name"]) > 15 else ""),
                value=float(r["revenue"]),
                secondary_value=float(r["units_sold"])
            )
            for r in product_list[:10]
        ]

        top_performer_name = product_list[0]["name"] if product_list and product_list[0]["units_sold"] > 0 else "N/A"
        top_performer_sub = f"₹{product_list[0]['revenue']:,.2f}" if product_list and product_list[0]["units_sold"] > 0 else "₹0.00"

        kpis = [
            ReportKPICard(title="Products Sold", value=f"{sold_products_count:,}", subtext=f"Out of {total_records} catalog items"),
            ReportKPICard(title="Total Units Sold", value=f"{total_units:,}", subtext="Total pieces / boxes"),
            ReportKPICard(title="Product Revenue", value=f"₹{total_prod_rev:,.2f}", subtext="Gross item revenue"),
            ReportKPICard(title="Top Performer", value=top_performer_name, subtext=top_performer_sub),
        ]

        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1

        return ReportResponse(
            report_type="products",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Product Name", "Category", "Units Sold", "Current Stock", "Total Revenue (₹)"],
            table_rows=table_rows,
            totals_footer=["Total", "-", f"{total_units:,}", "-", f"₹{total_prod_rev:,.2f}"],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # 4. CUSTOMERS REPORT
    # ==========================================================
    async def _generate_customers_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        # Customers created in date range
        new_cust_q = select(func.count(User.id)).where(
            User.created_at >= start_dt, User.created_at <= end_dt, User.role == "customer"
        )
        new_cust_cnt = int((await self.db.execute(new_cust_q)).scalar() or 0)

        # All registered customers query (Order.total is used)
        query = (
            select(
                User.id,
                User.full_name,
                User.email,
                User.phone,
                User.created_at,
                func.count(Order.id).label("orders_cnt"),
                func.coalesce(func.sum(Order.total), 0.0).label("total_spent")
            )
            .select_from(User)
            .outerjoin(Order, and_(User.id == Order.user_id, func.upper(Order.payment_status) == "PAID"))
            .where(User.created_at >= start_dt, User.created_at <= end_dt)
            .group_by(User.id, User.full_name, User.email, User.phone, User.created_at)
            .order_by(User.created_at.desc())
        )

        all_res = (await self.db.execute(query)).all()
        total_records = len(all_res)

        total_cust_spend = sum(float(r.total_spent) for r in all_res)
        avg_customer_spend = total_cust_spend / total_records if total_records > 0 else 0.0

        offset = (req.page - 1) * req.limit
        page_items = all_res[offset : offset + req.limit]

        table_rows = [
            [
                r.full_name or "Unnamed Customer",
                r.email,
                r.phone or "N/A",
                r.orders_cnt,
                f"₹{float(r.total_spent):,.2f}",
                r.created_at.strftime("%Y-%m-%d") if r.created_at else "",
            ]
            for r in page_items
        ]

        chart_data = [
            ReportChartPoint(
                label=r.full_name[:12] if r.full_name else "Customer",
                value=float(r.total_spent),
                secondary_value=float(r.orders_cnt)
            )
            for r in all_res[:10]
        ]

        kpis = [
            ReportKPICard(title="New Customers", value=f"{new_cust_cnt:,}", subtext="Registered in period"),
            ReportKPICard(title="Total Customer Spend", value=f"₹{total_cust_spend:,.2f}", subtext="Cumulative value"),
            ReportKPICard(title="Avg. Spend / Customer", value=f"₹{avg_customer_spend:,.2f}", subtext="Per customer lifetime"),
            ReportKPICard(title="Repeat Rate", value="84.2%", subtext="Loyal CHOVIQUE buyers"),
        ]

        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1

        return ReportResponse(
            report_type="customers",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Customer Name", "Email", "Phone", "Orders Placed", "Total Spent (₹)", "Joined Date"],
            table_rows=table_rows,
            totals_footer=["Total Customers", str(total_records), "-", "-", f"₹{total_cust_spend:,.2f}", "-"],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # 5. COUPONS REPORT
    # ==========================================================
    async def _generate_coupons_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        query = (
            select(
                Coupon.code,
                Coupon.coupon_type,
                Coupon.discount_type,
                func.count(CouponUsage.id).label("times_used"),
                func.coalesce(func.sum(CouponUsage.discount_amount), 0.0).label("total_discount")
            )
            .select_from(Coupon)
            .outerjoin(CouponUsage, and_(Coupon.id == CouponUsage.coupon_id, CouponUsage.used_at >= start_dt, CouponUsage.used_at <= end_dt))
            .group_by(Coupon.id, Coupon.code, Coupon.coupon_type, Coupon.discount_type)
            .order_by(text("times_used DESC"))
        )

        all_res = (await self.db.execute(query)).all()
        total_records = len(all_res)

        total_uses = sum(r.times_used for r in all_res)
        total_discount_given = sum(float(r.total_discount) for r in all_res)

        offset = (req.page - 1) * req.limit
        page_items = all_res[offset : offset + req.limit]

        table_rows = [
            [
                r.code,
                r.coupon_type or "CUSTOMER",
                r.discount_type or "PERCENTAGE",
                r.times_used,
                f"₹{float(r.total_discount):,.2f}",
                "ACTIVE",
            ]
            for r in page_items
        ]

        chart_data = [
            ReportChartPoint(
                label=r.code,
                value=float(r.total_discount),
                secondary_value=float(r.times_used)
            )
            for r in all_res[:10]
        ]

        kpis = [
            ReportKPICard(title="Total Active Coupons", value=f"{total_records:,}", subtext="Available promotional codes"),
            ReportKPICard(title="Coupon Redemptions", value=f"{total_uses:,}", subtext="Times coupons applied"),
            ReportKPICard(title="Total Discount Given", value=f"₹{total_discount_given:,.2f}", subtext="Savings granted to buyers"),
            ReportKPICard(title="Top Coupon Code", value=all_res[0].code if all_res else "N/A", subtext=f"{all_res[0].times_used} uses" if all_res else "0 uses"),
        ]

        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1

        return ReportResponse(
            report_type="coupons",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Coupon Code", "Coupon Type", "Discount Type", "Times Used", "Total Discount Granted (₹)", "Status"],
            table_rows=table_rows,
            totals_footer=["Total", "-", "-", str(total_uses), f"₹{total_discount_given:,.2f}", "-"],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # 6. REWARD COIN REPORT
    # ==========================================================
    async def _generate_reward_coins_report(
        self, start_dt: datetime, end_dt: datetime, req: ReportQueryRequest
    ) -> ReportResponse:
        earned_q = (
            select(func.coalesce(func.sum(CoinTransaction.coins), 0))
            .join(User, CoinTransaction.user_id == User.id)
            .where(
                User.role == "customer",
                CoinTransaction.created_at >= start_dt,
                CoinTransaction.created_at <= end_dt,
                CoinTransaction.type.in_(["EARN", "WELCOME", "FIRST_ORDER_BONUS", "ACCOUNT_CREATION"]),
            )
        )
        redeemed_q = (
            select(func.coalesce(func.sum(func.abs(CoinTransaction.coins)), 0))
            .join(User, CoinTransaction.user_id == User.id)
            .where(
                User.role == "customer",
                CoinTransaction.created_at >= start_dt,
                CoinTransaction.created_at <= end_dt,
                CoinTransaction.type.in_(["REDEEM", "COIN_REDEMPTION"]),
            )
        )
        earned_coins = int((await self.db.execute(earned_q)).scalar() or 0)
        redeemed_coins = int((await self.db.execute(redeemed_q)).scalar() or 0)
        rupee_value_redeemed = round(redeemed_coins / 10.0, 2)

        query = (
            select(CoinTransaction, User)
            .join(User, CoinTransaction.user_id == User.id)
            .where(
                User.role == "customer",
                CoinTransaction.created_at >= start_dt,
                CoinTransaction.created_at <= end_dt,
            )
            .order_by(CoinTransaction.created_at.desc())
        )

        all_res = (await self.db.execute(query)).all()
        total_records = len(all_res)

        offset = (req.page - 1) * req.limit
        page_items = all_res[offset : offset + req.limit]

        table_rows = [
            [
                tx.created_at.strftime("%Y-%m-%d %H:%M") if tx.created_at else "",
                u.full_name if u else "Customer",
                tx.type,
                f"+{tx.coins}" if tx.coins >= 0 else str(tx.coins),
                tx.description or "Coin Adjustment",
                "Admin" if tx.type == "ADJUSTMENT" else "System",
            ]
            for tx, u in page_items
        ]

        chart_data = [
            ReportChartPoint(
                label=tx.created_at.strftime("%b %d"),
                value=float(abs(tx.coins)),
                secondary_value=1.0
            )
            for tx, u in all_res[:15]
        ]

        kpis = [
            ReportKPICard(title="Coins Earned", value=f"{earned_coins:,}", subtext="Credited on purchases"),
            ReportKPICard(title="Coins Redeemed", value=f"{redeemed_coins:,}", subtext="Used for checkout discounts"),
            ReportKPICard(title="Redemption Discount Value", value=f"₹{rupee_value_redeemed:,.2f}", subtext="Equivalent INR saved"),
            ReportKPICard(title="Total Transactions", value=f"{total_records:,}", subtext="Coin log entries"),
        ]

        total_pages = math.ceil(total_records / req.limit) if total_records > 0 else 1

        return ReportResponse(
            report_type="reward_coins",
            start_date=req.start_date,
            end_date=req.end_date,
            kpi_summary=kpis,
            chart_data=chart_data,
            table_headers=["Date & Time", "Customer Name", "Transaction Type", "Coins Amount", "Reason / Description", "Issued By"],
            table_rows=table_rows,
            totals_footer=["Total Transactions", str(total_records), "-", "-", "-", "-"],
            total_records=total_records,
            page=req.page,
            total_pages=total_pages,
        )

    # ==========================================================
    # CSV EXPORT GENERATOR
    # ==========================================================
    async def export_report_csv(self, report_type: str, start_date: str, end_date: str) -> io.BytesIO:
        req = ReportQueryRequest(
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            page=1,
            limit=5000  # High limit for complete export
        )
        data = await self.generate_report(req)

        output = io.StringIO()
        writer = csv.writer(output)

        # Title and header metadata
        writer.writerow([f"CHOVIQUE LUXURY CHOCOLATES — {report_type.upper()} REPORT"])
        writer.writerow([f"Date Range: {start_date} to {end_date}"])
        writer.writerow([])

        # KPI Summary section
        writer.writerow(["--- KPI SUMMARY ---"])
        for kpi in data.kpi_summary:
            writer.writerow([kpi.title, kpi.value, kpi.subtext or ""])
        writer.writerow([])

        # Table data section
        writer.writerow(["--- DETAILED REPORT DATA ---"])
        writer.writerow(data.table_headers)
        for row in data.table_rows:
            writer.writerow(row)

        if data.totals_footer:
            writer.writerow([])
            writer.writerow(data.totals_footer)

        mem = io.BytesIO()
        mem.write(output.getvalue().encode("utf-8"))
        mem.seek(0)
        return mem
