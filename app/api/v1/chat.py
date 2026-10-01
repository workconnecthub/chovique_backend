from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.db.session import get_db
from app.models.offline_sale import OfflineSale
from app.models.order import Order
from app.models.product import Product
from app.models.user import User
from app.repositories.order_repository import OrderRepository
from app.repositories.product_repository import ProductRepository
from app.schemas.chat import ChatAction, ChatRequest, ChatResponse
from app.services.gemini_service import gemini_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chatbot"])


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Send a message to the Chovique AI assistant (Coco)",
    description=(
        "Public endpoint — accessible to guests, authenticated customers, store admins, and superadmins. "
        "Dynamically injects live database products, personal customer orders, admin inventory stats, "
        "or superadmin executive revenue metrics depending on verified user role. "
        "Returns the AI assistant's reply with interactive action redirect buttons."
    ),
)
async def chat(
    payload: ChatRequest,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """
    Send a message to Gemini and return Coco's role-aware reply with action buttons.

    - Message length is validated by the schema (max 2000 chars).
    - Conversation history (max 20 turns) is passed to preserve context.
    - Verified user role determines contextual database injection (Customer vs Admin vs Superadmin).
    - Admin queries pull real stock levels, low-stock alerts, and product creation guide.
    - Superadmin queries pull real lifetime revenue, today's sales, yesterday's sales, and daily history table.
    - Non-admins NEVER have access to admin or superadmin proprietary business data.
    """
    # 1. Determine verified user role & display name strictly from authenticated session
    effective_role = "guest"
    user_name = None

    if current_user:
        effective_role = str(getattr(current_user, "role", "customer")).lower().strip()
        user_name = current_user.full_name or getattr(current_user, "username", None) or "User"
    elif payload.customer_name:
        # Unauthenticated guests can supply a friendly name, but privilege is strictly locked to 'guest'
        user_name = payload.customer_name.strip()
        effective_role = "guest"

    logger.info(
        "Chat request received. role=%s, user=%s, message_len=%d, history_turns=%d",
        effective_role,
        user_name,
        len(payload.message),
        len(payload.history),
    )

    try:
        catalog: list[dict] = []
        user_orders: list[dict] = []
        admin_context: Optional[dict] = None
        superadmin_context: Optional[dict] = None

        # =====================================================================
        # ROLE: SUPERADMIN (Executive Revenue & Analytics)
        # =====================================================================
        if effective_role == "superadmin":
            try:
                now_utc = datetime.now(timezone.utc)
                today_dt = now_utc.date()
                yesterday_dt = today_dt - timedelta(days=1)

                # 1. Lifetime online revenue & orders
                online_rev_res = await db.execute(
                    select(func.coalesce(func.sum(Order.total), 0.0), func.count(Order.id))
                )
                online_row = online_rev_res.one()
                online_rev = float(online_row[0] or 0.0)
                online_orders = int(online_row[1] or 0)

                # 2. Lifetime offline revenue & sales
                offline_rev_res = await db.execute(
                    select(func.coalesce(func.sum(OfflineSale.total_price), 0.0), func.count(OfflineSale.id))
                )
                offline_row = offline_rev_res.one()
                offline_rev = float(offline_row[0] or 0.0)
                offline_sales = int(offline_row[1] or 0)

                lifetime_revenue = online_rev + offline_rev
                total_transactions = online_orders + offline_sales

                # 3. Grouped daily breakdown for the past 45 days
                cutoff_dt = today_dt - timedelta(days=45)

                online_daily_res = await db.execute(
                    select(func.date(Order.created_at).label("dt"), func.count(Order.id), func.sum(Order.total))
                    .where(func.date(Order.created_at) >= cutoff_dt)
                    .group_by(func.date(Order.created_at))
                )
                daily_data: dict[str, dict] = {}
                for row in online_daily_res.all():
                    dt_str = str(row[0])
                    daily_data[dt_str] = {
                        "online_rev": float(row[2] or 0.0),
                        "offline_rev": 0.0,
                        "orders": int(row[1] or 0),
                    }

                offline_daily_res = await db.execute(
                    select(func.date(OfflineSale.created_at).label("dt"), func.count(OfflineSale.id), func.sum(OfflineSale.total_price))
                    .where(func.date(OfflineSale.created_at) >= cutoff_dt)
                    .group_by(func.date(OfflineSale.created_at))
                )
                for row in offline_daily_res.all():
                    dt_str = str(row[0])
                    if dt_str not in daily_data:
                        daily_data[dt_str] = {"online_rev": 0.0, "offline_rev": 0.0, "orders": 0}
                    daily_data[dt_str]["offline_rev"] += float(row[2] or 0.0)
                    daily_data[dt_str]["orders"] += int(row[1] or 0)

                today_str = str(today_dt)
                yesterday_str = str(yesterday_dt)

                today_info = daily_data.get(today_str, {"online_rev": 0.0, "offline_rev": 0.0, "orders": 0})
                today_sales = today_info["online_rev"] + today_info["offline_rev"]
                today_orders = today_info["orders"]

                yesterday_info = daily_data.get(yesterday_str, {"online_rev": 0.0, "offline_rev": 0.0, "orders": 0})
                yesterday_sales = yesterday_info["online_rev"] + yesterday_info["offline_rev"]
                yesterday_orders = yesterday_info["orders"]

                # Current month sales
                month_prefix = today_dt.strftime("%Y-%m")
                month_sales = sum(
                    v["online_rev"] + v["offline_rev"]
                    for k, v in daily_data.items()
                    if k.startswith(month_prefix)
                )
                month_orders = sum(
                    v["orders"]
                    for k, v in daily_data.items()
                    if k.startswith(month_prefix)
                )

                daily_lines = []
                for dt_key in sorted(daily_data.keys(), reverse=True):
                    entry = daily_data[dt_key]
                    t_rev = entry["online_rev"] + entry["offline_rev"]
                    daily_lines.append(
                        f"- {dt_key}: Total = ₹{t_rev:,.2f} ({entry['orders']} orders | Online: ₹{entry['online_rev']:,.2f}, Offline: ₹{entry['offline_rev']:,.2f})"
                    )

                superadmin_context = {
                    "lifetime_revenue": lifetime_revenue,
                    "online_revenue": online_rev,
                    "offline_revenue": offline_rev,
                    "total_transactions": total_transactions,
                    "online_orders": online_orders,
                    "offline_sales": offline_sales,
                    "today_date": today_dt.strftime("%d %B %Y"),
                    "today_sales": today_sales,
                    "today_orders": today_orders,
                    "yesterday_date": yesterday_dt.strftime("%d %B %Y"),
                    "yesterday_sales": yesterday_sales,
                    "yesterday_orders": yesterday_orders,
                    "month_name": today_dt.strftime("%B %Y"),
                    "month_sales": month_sales,
                    "month_orders": month_orders,
                    "daily_sales_table": "\n".join(daily_lines) if daily_lines else "No sales recorded in the past 45 days.",
                    "daily_data": daily_data,
                }
            except Exception as sa_err:
                logger.warning("Could not fetch superadmin context from database: %s", sa_err)

        # =====================================================================
        # ROLE: ADMIN (Inventory, Stock & Store Operations)
        # =====================================================================
        elif effective_role == "admin":
            try:
                # 1. Product stock breakdown
                prod_stmt = select(Product).order_by(Product.stock.asc())
                prod_res = await db.execute(prod_stmt)
                all_prods = prod_res.scalars().all()

                total_products = len(all_prods)
                total_units = sum(p.stock for p in all_prods)
                low_stock = [p for p in all_prods if p.stock <= 10 and p.stock > 0]
                out_of_stock = [p for p in all_prods if p.stock == 0]

                stock_lines = [
                    f"- **{p.name}**: {p.stock} units in stock (Price: ₹{p.price:.0f}) {'⚠️ [LOW STOCK]' if p.stock <= 10 else ''}"
                    for p in all_prods
                ]

                # 2. Store orders breakdown
                order_cnt_res = await db.execute(select(func.count(Order.id)))
                total_orders = int(order_cnt_res.scalar() or 0)

                pending_res = await db.execute(
                    select(func.count(Order.id)).where(Order.status.in_(["Processing", "Pending"]))
                )
                pending_orders = int(pending_res.scalar() or 0)

                delivered_res = await db.execute(
                    select(func.count(Order.id)).where(Order.status == "Delivered")
                )
                delivered_orders = int(delivered_res.scalar() or 0)

                admin_context = {
                    "total_products": total_products,
                    "total_units": total_units,
                    "low_stock_count": len(low_stock),
                    "low_stock_summary": ", ".join(f"{p.name} ({p.stock})" for p in low_stock) or "None",
                    "out_of_stock_count": len(out_of_stock),
                    "out_of_stock_summary": ", ".join(p.name for p in out_of_stock) or "None",
                    "stock_lines": "\n".join(stock_lines),
                    "total_orders": total_orders,
                    "pending_orders": pending_orders,
                    "delivered_orders": delivered_orders,
                }
            except Exception as ad_err:
                logger.warning("Could not fetch admin context from database: %s", ad_err)

        # =====================================================================
        # ROLE: DELIVERY PARTNER (Assigned Orders, Queue, Route, History)
        # =====================================================================
        elif effective_role in ("delivery", "delivery_partner"):
            try:
                partner_user_id = current_user.id if current_user else None
                partner_orders = []
                if partner_user_id:
                    stmt = select(Order).where(Order.delivery_boy_id == partner_user_id)
                    res = await db.execute(stmt.order_by(Order.created_at.desc()))
                    partner_orders = res.scalars().all()

                assigned_orders = [o for o in partner_orders if o.fulfillment_status == "ASSIGNED"]
                in_progress_orders = [o for o in partner_orders if o.fulfillment_status in ("ACCEPTED", "PICKED_UP", "OUT_FOR_DELIVERY")]
                delivered_orders = [o for o in partner_orders if o.fulfillment_status == "DELIVERED"]

                delivery_context = {
                    "total_assigned": len(partner_orders),
                    "queue_count": len(assigned_orders),
                    "in_progress_count": len(in_progress_orders),
                    "delivered_count": len(delivered_orders),
                    "assigned_orders_summary": [
                        {
                            "id": o.id,
                            "customer": o.shipping_name or (o.user.full_name if o.user else "Customer"),
                            "area": o.shipping_area or o.shipping_city or "Local",
                            "status": o.fulfillment_status,
                            "total": f"₹{o.total:.0f}" if o.total else "₹0",
                        }
                        for o in assigned_orders[:5]
                    ],
                    "in_progress_summary": [
                        {
                            "id": o.id,
                            "customer": o.shipping_name or (o.user.full_name if o.user else "Customer"),
                            "area": o.shipping_area or o.shipping_city or "Local",
                            "status": o.fulfillment_status,
                            "total": f"₹{o.total:.0f}" if o.total else "₹0",
                        }
                        for o in in_progress_orders[:5]
                    ],
                    "delivered_summary": [
                        {
                            "id": o.id,
                            "customer": o.shipping_name or (o.user.full_name if o.user else "Customer"),
                            "total": f"₹{o.total:.0f}" if o.total else "₹0",
                        }
                        for o in delivered_orders[:5]
                    ],
                    "hub_name": "Chovique Central Store & Fulfillment Hub",
                    "hub_address": "Plot 42, Jubilee Hills Road No. 36, Hyderabad, Telangana 500033",
                    "hub_hours": "09:00 AM – 10:00 PM (Daily Express)",
                }
            except Exception as deliv_err:
                logger.warning("Could not fetch delivery context from database: %s", deliv_err)

        # =====================================================================
        # ROLE: CUSTOMER / GUEST (Catalog & Personal Orders)
        # =====================================================================
        else:
            try:
                prod_repo = ProductRepository(db)
                prod_res = await prod_repo.get_all(per_page=50)
                for p in prod_res.get("items", []):
                    cat_name = getattr(p, "category", "") or (p.category_rel.name if getattr(p, "category_rel", None) else "")
                    catalog.append({
                        "id": str(p.id),
                        "name": p.name,
                        "price": f"₹{p.price:.0f}" if p.price else "₹0",
                        "category": cat_name,
                        "image": p.image or "",
                        "description": (p.description or "")[:200],
                        "is_bestseller": bool(p.is_bestseller),
                        "is_featured": bool(p.is_featured),
                        "rating": float(p.rating or 0.0),
                    })
            except Exception as p_err:
                logger.warning("Could not fetch products for chatbot context: %s", p_err)

            if current_user:
                try:
                    order_repo = OrderRepository(db)
                    orders = await order_repo.get_user_orders(current_user.id)
                    for o in orders[:5]:
                        items_desc = [
                            f"{it.product.name if it.product else 'Chocolate'} x{it.quantity} (₹{it.price:.0f})"
                            for it in (o.items or [])
                        ]
                        user_orders.append({
                            "order_id": o.id,
                            "date": o.created_at.strftime("%d %b %Y") if o.created_at else "Recently",
                            "status": o.status or "Processing",
                            "total": f"₹{o.total:.0f}" if o.total else "₹0",
                            "items": items_desc,
                        })
                except Exception as o_err:
                    logger.warning("Could not fetch user orders for chatbot context: %s", o_err)

        history_dicts = [
            {"role": turn.role, "content": turn.content}
            for turn in payload.history
        ]

        # Call Gemini service with role-specific database context
        reply = await gemini_service.send_message(
            message=payload.message,
            history=history_dicts,
            customer_name=user_name,
            customer_orders=user_orders,
            products_catalog=catalog,
            role=effective_role,
            admin_context=admin_context,
            superadmin_context=superadmin_context,
            delivery_context=delivery_context,
        )

        # Extract actions formatted like [Action: Label -> /url] or [Button: Label -> /url]
        actions: list[ChatAction] = []
        action_pattern = re.compile(
            r"\[(?:Action|Button):\s*([^->\]]+?)\s*->\s*([^\]]+?)\]",
            re.IGNORECASE,
        )

        seen_urls: set[str] = set()
        for match in action_pattern.finditer(reply):
            lbl = match.group(1).strip()
            dest_url = match.group(2).strip()
            if dest_url and dest_url not in seen_urls:
                seen_urls.add(dest_url)
                icon = "arrow"
                if "/superadmin" in dest_url:
                    if "revenue" in dest_url:
                        icon = "revenue"
                    elif "sales" in dest_url:
                        icon = "sales"
                    elif "reports" in dest_url:
                        icon = "reports"
                    else:
                        icon = "dashboard"
                elif "/admin" in dest_url:
                    if "products" in dest_url or "inventory" in dest_url:
                        icon = "warehouse"
                    elif "orders" in dest_url:
                        icon = "package"
                    elif "offline" in dest_url:
                        icon = "receipt"
                    elif "complaints" in dest_url or "tickets" in dest_url:
                        icon = "help"
                    else:
                        icon = "dashboard"
                elif "/delivery" in dest_url:
                    if "tab=queue" in dest_url:
                        icon = "package"
                    elif "tab=route" in dest_url:
                        icon = "route"
                    elif "tab=history" in dest_url:
                        icon = "award"
                    elif "tab=profile" in dest_url:
                        icon = "user"
                    else:
                        icon = "navigation"
                elif "/shop" in dest_url:
                    icon = "shop"
                elif "/product/" in dest_url:
                    icon = "product"
                elif "section=orders" in dest_url or "section=order" in dest_url:
                    icon = "package"
                elif "section=rewards" in dest_url or "section=coins" in dest_url:
                    icon = "coins"
                elif "section=coupons" in dest_url:
                    icon = "tag"
                elif "section=help" in dest_url or "/contact" in dest_url:
                    icon = "help"
                elif "/cart" in dest_url:
                    icon = "cart"
                elif "/wishlist" in dest_url:
                    icon = "heart"

                actions.append(ChatAction(label=lbl, url=dest_url, icon=icon))

        # Strip the raw [Action: ...] tags from the visible text for clean presentation
        clean_reply = action_pattern.sub("", reply).strip()

        # Fallback enrichment: Ensure tailored action buttons are ALWAYS attached based on role and query
        msg_lower = payload.message.lower()
        reply_lower = clean_reply.lower()

        if effective_role == "superadmin":
            if any(k in msg_lower for k in ["revenue", "sales", "sale", "today", "yesterday", "september", "14", "month", "money", "earn"]):
                rev_url = "/superadmin?section=revenue"
                if rev_url not in seen_urls:
                    actions.append(ChatAction(label="Revenue Analytics", url=rev_url, icon="revenue"))
                    seen_urls.add(rev_url)
                sales_url = "/superadmin?section=sales-comparison"
                if sales_url not in seen_urls and len(actions) < 3:
                    actions.append(ChatAction(label="Sales Analytics", url=sales_url, icon="sales"))
                    seen_urls.add(sales_url)

            if any(k in msg_lower for k in ["report", "reports", "export", "download", "sheet"]):
                rep_url = "/superadmin?section=reports"
                if rep_url not in seen_urls and len(actions) < 3:
                    actions.append(ChatAction(label="Reports & Analytics", url=rep_url, icon="reports"))
                    seen_urls.add(rep_url)

            if not actions:
                actions.append(ChatAction(label="Revenue Analytics", url="/superadmin?section=revenue", icon="revenue"))
                actions.append(ChatAction(label="Enterprise Overview", url="/superadmin?section=enterprise", icon="dashboard"))

        elif effective_role == "admin":
            if any(k in msg_lower for k in ["product", "products", "stock", "stocks", "inventory", "add", "steps", "chocolate"]):
                prod_url = "/admin?section=products"
                if prod_url not in seen_urls:
                    actions.append(ChatAction(label="Manage Products & Stock", url=prod_url, icon="warehouse"))
                    seen_urls.add(prod_url)

            if any(k in msg_lower for k in ["order", "orders", "pending", "status", "delivery", "dispatch"]):
                ord_url = "/admin?section=orders"
                if ord_url not in seen_urls and len(actions) < 3:
                    actions.append(ChatAction(label="Order Management", url=ord_url, icon="package"))
                    seen_urls.add(ord_url)

            if any(k in msg_lower for k in ["offline", "pos", "counter"]):
                off_url = "/admin?section=offline-sales"
                if off_url not in seen_urls and len(actions) < 3:
                    actions.append(ChatAction(label="Offline Sales Ledger", url=off_url, icon="receipt"))
                    seen_urls.add(off_url)

            if not actions:
                actions.append(ChatAction(label="Manage Products & Stock", url="/admin?section=products", icon="warehouse"))
                actions.append(ChatAction(label="Store Orders", url="/admin?section=orders", icon="package"))

        else:
            # Customer fallback actions
            is_product_query = any(k in msg_lower for k in [
                "chocolate", "chocolates", "product", "products", "hamper", "hampers",
                "truffle", "truffles", "price", "flavour", "flavor", "gift", "box",
                "dark", "milk", "white", "shop", "buy", "sell", "collection"
            ]) or any(k in reply_lower for k in ["artisan chocolate", "gift box", "shop page", "collection"])

            if is_product_query and "/shop" not in seen_urls:
                actions.append(ChatAction(label="Visit Shop Page", url="/shop", icon="shop"))
                seen_urls.add("/shop")

            is_order_query = any(k in msg_lower for k in [
                "order", "orders", "track", "tracking", "status", "shipment", "delivery"
            ])
            if is_order_query and "/dashboard?section=orders" not in seen_urls:
                actions.append(ChatAction(label="Track Orders in Dashboard", url="/dashboard?section=orders", icon="package"))
                seen_urls.add("/dashboard?section=orders")

            if any(k in msg_lower for k in ["coin", "coins", "wallet", "rewards", "points"]):
                if "/dashboard?section=rewards" not in seen_urls:
                    actions.append(ChatAction(label="View Rewards & Coins", url="/dashboard?section=rewards", icon="coins"))
                    seen_urls.add("/dashboard?section=rewards")

            if any(k in msg_lower for k in ["coupon", "coupons", "discount", "promo", "voucher"]):
                if "/dashboard?section=coupons" not in seen_urls:
                    actions.append(ChatAction(label="View Available Coupons", url="/dashboard?section=coupons", icon="tag"))
                    seen_urls.add("/dashboard?section=coupons")

            if any(k in msg_lower for k in ["help", "support", "contact", "issue", "problem", "refund", "return"]):
                if "/dashboard?section=help" not in seen_urls:
                    actions.append(ChatAction(label="Help & Support", url="/dashboard?section=help", icon="help"))
                    seen_urls.add("/dashboard?section=help")

            if not actions:
                actions.append(ChatAction(label="Visit Shop Page", url="/shop", icon="shop"))

        return ChatResponse(reply=clean_reply, actions=actions)

    except ValueError as exc:
        logger.error("Chatbot configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The AI assistant is not configured yet. Please contact support or try again later.",
        )
    except RuntimeError as exc:
        logger.error("Chatbot runtime error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Unexpected chatbot error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Our AI assistant encountered an unexpected issue. Please try again or contact us through the website.",
        )
