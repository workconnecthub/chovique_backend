import re
from datetime import date, datetime
from typing import Optional, Literal

from sqlalchemy import select, func, or_, and_, cast, Date, Text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models.order import Order, OrderItem, OrderSequence


class OrderRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_next_order_id(self) -> str:
        """
        Generate atomic, sequential order IDs in the format ORD-00001-D001.
        Uses row locking on OrderSequence (with_for_update) for thread and process concurrency safety.
        """
        stmt = select(OrderSequence).where(OrderSequence.id == 1)
        bind_engine = getattr(self.db, "bind", None)
        engine_name = getattr(bind_engine, "name", "") if bind_engine else ""
        if engine_name and engine_name != "sqlite":
            stmt = stmt.with_for_update()

        result = await self.db.execute(stmt)
        seq_row = result.scalar_one_or_none()

        if seq_row is None:
            # Initialize from existing orders in database
            order_stmt = select(Order.id)
            order_res = await self.db.execute(order_stmt)
            existing_ids = order_res.scalars().all()

            max_seq = 0
            for oid in existing_ids:
                match = re.search(r"ORD-(\d+)", str(oid))
                if match:
                    try:
                        val = int(match.group(1))
                        if val > max_seq:
                            max_seq = val
                    except ValueError:
                        pass

            seq_row = OrderSequence(id=1, current_seq=max_seq)
            self.db.add(seq_row)
            await self.db.flush()

        seq_row.current_seq += 1
        next_seq = seq_row.current_seq
        await self.db.flush()

        seq_5digit = f"{next_seq:05d}"
        seq_3digit = f"{(next_seq % 1000):03d}"
        return f"ORD-{seq_5digit}-D{seq_3digit}"

    async def create_order(
        self,
        user_id: str,
        total: float,
        subtotal: float,
        discount: float,
        shipping: float,
        tax: float,
        shipping_address: dict,
        delivery_option: str,
        payment_method: str,
        items_data: list[dict],
        coupon_code: str | None = None,
        coupon_discount: float = 0.0,
        coins_used: int = 0,
        coin_discount: float = 0.0,
        coins_earned: int = 0,
        payment_status: str = "PENDING",
        fulfillment_type: str = "LOCAL",
        shipping_provider: str = "INTERNAL",
        fulfillment_status: str = "UNASSIGNED",
        delivery_boy_id: str | None = None,
        store_location_id: str | None = None,
        shipping_snapshot: dict | None = None,
        commit: bool = True,
    ) -> Order:
        order_id = await self.generate_next_order_id()
        snap = shipping_snapshot or (shipping_address if isinstance(shipping_address, dict) else {})

        order = Order(
            id=order_id,
            user_id=user_id,
            total=total,
            subtotal=subtotal,
            discount=discount,
            coupon_code=coupon_code,
            coupon_discount=coupon_discount,
            coins_used=coins_used,
            coin_discount=coin_discount,
            coins_earned=coins_earned,
            shipping=shipping,
            tax=tax,
            shipping_address=shipping_address,
            delivery_option=delivery_option,
            payment_method=payment_method,
            status="Processing",
            payment_status=payment_status,
            paid_at=func.now() if payment_status.upper() == "PAID" else None,
            # Dual-Mode Fulfillment & Logistics
            store_location_id=store_location_id,
            fulfillment_type=fulfillment_type or "LOCAL",
            shipping_provider=shipping_provider or "INTERNAL",
            fulfillment_status=fulfillment_status or "UNASSIGNED",
            delivery_boy_id=delivery_boy_id,
            # Authoritative Immutable Shipping Snapshot
            shipping_name=snap.get("name") or snap.get("full_name"),
            shipping_phone=snap.get("phone"),
            shipping_house_number=snap.get("house_number"),
            shipping_street=snap.get("street"),
            shipping_area=snap.get("area"),
            shipping_landmark=snap.get("landmark"),
            shipping_city=snap.get("city"),
            shipping_district=snap.get("district"),
            shipping_state=snap.get("state"),
            shipping_pincode=snap.get("zip") or snap.get("pincode") or snap.get("zip_code"),
            shipping_latitude=snap.get("latitude"),
            shipping_longitude=snap.get("longitude"),
            shipping_formatted_address=snap.get("formatted_address"),
            shipping_google_place_id=snap.get("google_place_id"),
            shipping_location_source=snap.get("location_source") or "MANUAL",
            shipping_location_verified=bool(snap.get("location_verified", False)),
            shipping_delivery_charge=shipping,
            shipping_confirmed_at=func.now(),
        )
        self.db.add(order)
        await self.db.flush()

        for item_info in items_data:
            item = OrderItem(
                order_id=order.id,
                product_id=item_info["product_id"],
                quantity=item_info["quantity"],
                price=item_info["price"],
            )
            self.db.add(item)

        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

        try:
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)
            await notif_service.notify_new_order(order.id, order.id, order.total, commit=commit)
            if coupon_code:
                await notif_service.notify_coupon_usage(coupon_code, order.id, commit=commit)
            
            # Check stock levels for low stock alerts
            for item_info in items_data:
                pid = item_info.get("product_id")
                if pid:
                    from app.models.product import Product
                    prod_res = await self.db.execute(select(Product).where(Product.id == pid))
                    prod = prod_res.scalar_one_or_none()
                    if prod and prod.stock <= 5:
                        await notif_service.notify_low_stock(prod.id, prod.name, prod.stock, commit=commit)
        except Exception:
            pass

        # Re-fetch with loaded items and product relationships
        return await self.get_by_id(order.id)

    async def get_user_orders(self, user_id: str) -> list[Order]:
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.delivery_boy),
                selectinload(Order.store_location),
            )
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_all_orders_for_admin(self) -> list[Order]:
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.delivery_boy),
                selectinload(Order.store_location),
            )
            .order_by(Order.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, order_id: str) -> Order | None:
        result = await self.db.execute(
            select(Order)
            .options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.delivery_boy),
                selectinload(Order.store_location),
            )
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    # ──────────────────────────────────────────────────────────────
    # Admin list / search / pagination
    # ──────────────────────────────────────────────────────────────

    def _build_admin_filter(
        self,
        query,
        *,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
        fulfillment_type: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ):
        """Attach WHERE clauses to the base query (reused by list and count)."""
        if status and status.upper() != "ALL":
            if status in ("Out_For_Delivery", "Out for Delivery"):
                query = query.where(Order.status.in_(["Out_For_Delivery", "Out for Delivery"]))
            else:
                query = query.where(func.lower(Order.status) == status.lower())

        if payment_status and payment_status.upper() != "ALL":
            p_val = payment_status.strip().lower()
            if p_val in ("refund pending", "refund_pending"):
                query = query.where(func.lower(Order.payment_status).in_(["refund pending", "refund_pending"]))
            elif p_val in ("partially refunded", "partially_refunded"):
                query = query.where(func.lower(Order.payment_status).in_(["partially refunded", "partially_refunded"]))
            else:
                query = query.where(func.lower(Order.payment_status) == p_val)

        if fulfillment_type and fulfillment_type.upper() != "ALL":
            query = query.where(func.upper(Order.fulfillment_type) == fulfillment_type.upper())

        if search and search.strip():
            like = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Order.id).like(like),
                    func.lower(cast(Order.shipping_address, type_=Text)).like(like),
                    func.lower(Order.shipping_name).like(like),
                    func.lower(Order.shipping_phone).like(like),
                )
            )

        if date_from:
            query = query.where(cast(Order.created_at, Date) >= date_from)
        if date_to:
            query = query.where(cast(Order.created_at, Date) <= date_to)

        return query

    async def admin_list_orders(
        self,
        *,
        status: Optional[str] = None,
        payment_status: Optional[str] = None,
        fulfillment_type: Optional[str] = None,
        search: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[Order], int]:
        """
        Return (orders_list, total_count) for the admin order management page.
        Supports filtering, full-text search on order ID and shipping address,
        date range, field sorting, and offset pagination.
        """
        SORTABLE = {
            "created_at": Order.created_at,
            "total": Order.total,
            "status": Order.status,
            "payment_status": Order.payment_status,
            "fulfillment_type": Order.fulfillment_type,
        }
        sort_col = SORTABLE.get(sort_by, Order.created_at)
        sort_expr = sort_col.asc() if sort_order.lower() == "asc" else sort_col.desc()

        count_q = self._build_admin_filter(
            select(func.count()).select_from(Order),
            status=status,
            payment_status=payment_status,
            fulfillment_type=fulfillment_type,
            search=search,
            date_from=date_from,
            date_to=date_to,
        )
        count_result = await self.db.execute(count_q)
        total = count_result.scalar_one()

        data_q = self._build_admin_filter(
            select(Order).options(
                selectinload(Order.items).selectinload(OrderItem.product),
                selectinload(Order.delivery_boy),
                selectinload(Order.store_location),
            ),
            status=status,
            payment_status=payment_status,
            fulfillment_type=fulfillment_type,
            search=search,
            date_from=date_from,
            date_to=date_to,
        ).order_by(sort_expr)

        offset = (page - 1) * limit
        data_q = data_q.offset(offset).limit(limit)

        data_result = await self.db.execute(data_q)
        orders = list(data_result.scalars().all())

        return orders, total

    async def admin_count_summary(self) -> dict:
        """
        Return KPI counts for all fulfillment/payment statuses, local/courier split, and total revenue.
        Used to populate the summary block in AdminOrderListResponse.
        """
        fulfillment_q = await self.db.execute(
            select(Order.status, func.count().label("cnt"))
            .group_by(Order.status)
        )
        f_counts_lower = {str(row.status or "").lower(): row.cnt for row in fulfillment_q}

        payment_q = await self.db.execute(
            select(Order.payment_status, func.count().label("cnt"))
            .group_by(Order.payment_status)
        )
        p_counts_lower = {str(row.payment_status or "").lower(): row.cnt for row in payment_q}

        revenue_q = await self.db.execute(
            select(func.coalesce(func.sum(Order.total), 0.0))
            .where(Order.status != "Cancelled")
        )
        total_revenue = float(revenue_q.scalar_one())

        total_orders_q = await self.db.execute(select(func.count()).select_from(Order))
        total_orders = total_orders_q.scalar_one()

        # Local vs Courier orders count
        local_orders_q = await self.db.execute(
            select(func.count(Order.id)).where(func.upper(Order.fulfillment_type) == "LOCAL")
        )
        local_orders = local_orders_q.scalar_one()

        courier_orders_q = await self.db.execute(
            select(func.count(Order.id)).where(func.upper(Order.fulfillment_type) == "COURIER")
        )
        courier_orders = courier_orders_q.scalar_one()

        # Unassigned local orders (active orders needing delivery executive assignment)
        unassigned_local_q = await self.db.execute(
            select(func.count(Order.id)).where(
                func.upper(Order.fulfillment_type) == "LOCAL",
                (Order.delivery_boy_id.is_(None)) | (Order.fulfillment_status.in_(["UNASSIGNED", "REJECTED"])),
                Order.status.notin_(["Delivered", "Cancelled", "Returned"]),
            )
        )
        unassigned_local = unassigned_local_q.scalar_one()

        out_for_delivery_cnt = f_counts_lower.get("out_for_delivery", 0) + f_counts_lower.get("out for delivery", 0)
        refund_pending_cnt = p_counts_lower.get("refund pending", 0) + p_counts_lower.get("refund_pending", 0)
        partially_refunded_cnt = p_counts_lower.get("partially refunded", 0) + p_counts_lower.get("partially_refunded", 0)

        return {
            "total_orders": total_orders,
            "processing": f_counts_lower.get("processing", 0),
            "confirmed": f_counts_lower.get("confirmed", 0),
            "shipped": f_counts_lower.get("shipped", 0),
            "out_for_delivery": out_for_delivery_cnt,
            "delivered": f_counts_lower.get("delivered", 0),
            "cancelled": f_counts_lower.get("cancelled", 0),
            "pending": f_counts_lower.get("pending", 0),
            "returned": f_counts_lower.get("returned", 0),
            "pending_payment": p_counts_lower.get("pending", 0),
            "paid": p_counts_lower.get("paid", 0),
            "failed_payment": p_counts_lower.get("failed", 0),
            "refunded": p_counts_lower.get("refunded", 0),
            "refund_pending": refund_pending_cnt,
            "partially_refunded": partially_refunded_cnt,
            "total_revenue": total_revenue,
            "local_orders": local_orders,
            "courier_orders": courier_orders,
            "unassigned_local": unassigned_local,
        }
