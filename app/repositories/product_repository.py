import math
from typing import Any

from sqlalchemy import func, or_, select, update, delete, cast, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product import Product


class ProductRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    # ==========================================================
    # Get All (Paginated + Filtered)
    # ==========================================================

    async def get_all(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        availability: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        min_rating: float | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 12,
    ) -> dict[str, Any]:

        query = select(Product).where(Product.is_active.is_(True))

        # --- Filters ---

        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    Product.name.ilike(term),
                    Product.sku.ilike(term),
                    Product.description.ilike(term),
                    Product.ingredients.ilike(term),
                    Product.badge.ilike(term),
                )
            )

        if category and category != "all":
            from app.models.category import Category
            cat_term = category.strip()
            query = query.join(Product.category_rel, isouter=True).where(
                or_(
                    Product.category_id == cat_term,
                    Category.id == cat_term,
                    Category.slug == cat_term,
                    Category.slug.ilike(f"%{cat_term}%"),
                    Category.name.ilike(f"%{cat_term}%"),
                )
            )

        if availability and availability != "all":
            if availability in ("in_stock", "instock"):
                query = query.where(Product.is_available.is_(True), Product.stock > 0)
            elif availability in ("out_of_stock", "stock_out", "outofstock"):
                query = query.where(or_(Product.is_available.is_(False), Product.stock <= 0))

        if price_min is not None:
            query = query.where(Product.price >= float(price_min))

        if price_max is not None:
            query = query.where(Product.price <= float(price_max))

        if min_rating is not None:
            query = query.where(Product.rating >= float(min_rating))

        if sort in ("popularity", "bestseller"):
            query = query.where(
                or_(
                    Product.is_bestseller.is_(True),
                    Product.badge.in_(["Bestseller", "Premium", "Popular"]),
                )
            )
        elif sort in ("newest", "new"):
            query = query.where(
                or_(
                    Product.is_new_arrival.is_(True),
                    Product.badge.in_(["New", "New Arrival"]),
                )
            )

        # --- Count (before pagination) ---

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0

        # --- Sort ---

        sort_map = {
            "featured": (Product.is_featured.desc(), Product.sort_order.asc(), Product.id.asc()),
            "popularity": (Product.is_bestseller.desc(), Product.ratings_count.desc(), Product.sort_order.asc()),
            "bestseller": (Product.is_bestseller.desc(), Product.ratings_count.desc(), Product.sort_order.asc()),
            "price_asc": Product.price.asc(),
            "price_desc": Product.price.desc(),
            "rating": (Product.rating.desc(), Product.ratings_count.desc()),
            "newest": Product.created_at.desc(),
            "name_asc": Product.name.asc(),
            "name_desc": Product.name.desc(),
        }

        order = sort_map.get(sort, (Product.is_featured.desc(), Product.sort_order.asc(), Product.id.asc()))
        if isinstance(order, tuple):
            query = query.order_by(*order)
        else:
            query = query.order_by(order)

        # --- Pagination ---

        offset = (page - 1) * per_page
        query = query.offset(offset).limit(per_page)

        result = await self.db.execute(query)
        items = list(result.scalars().all())

        total_pages = math.ceil(total / per_page) if per_page > 0 else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # ==========================================================
    # Get By ID
    # ==========================================================

    async def get_by_id(self, product_id: str) -> Product | None:

        result = await self.db.execute(
            select(Product).where(Product.id == product_id)
        )

        return result.scalar_one_or_none()

    # ==========================================================
    # Get By Slug
    # ==========================================================

    async def get_by_slug(self, slug: str) -> Product | None:

        result = await self.db.execute(
            select(Product).where(Product.slug == slug)
        )

        return result.scalar_one_or_none()

    # ==========================================================
    # Get Featured (Top Rated)
    # ==========================================================

    async def get_featured(self, limit: int = 4) -> list[Product]:

        result = await self.db.execute(
            select(Product)
            .where(Product.is_active.is_(True))
            .order_by(Product.sort_order.asc(), Product.rating.desc())
            .limit(limit)
        )

        return list(result.scalars().all())

    # ==========================================================
    # Get Bestsellers
    # ==========================================================

    async def get_bestsellers(self, limit: int = 4) -> list[Product]:

        result = await self.db.execute(
            select(Product)
            .where(
                Product.is_active.is_(True),
                or_(
                    Product.badge.in_(["Bestseller", "Premium"]),
                    Product.is_bestseller.is_(True),
                ),
                or_(Product.badge.is_(None), Product.badge.notin_(["Limited", "Limited Edition"])),
            )
            .order_by(Product.rating.desc())
            .limit(limit)
        )

        return list(result.scalars().all())

    # ==========================================================
    # Get New Arrivals
    # ==========================================================

    async def get_new_arrivals(self, limit: int = 4) -> list[Product]:

        result = await self.db.execute(
            select(Product)
            .where(
                Product.is_active.is_(True),
                or_(
                    Product.badge == "New",
                    Product.is_new_arrival.is_(True),
                ),
                or_(Product.badge.is_(None), Product.badge.notin_(["Limited", "Limited Edition"])),
            )
            .order_by(Product.created_at.desc())
            .limit(limit)
        )

        return list(result.scalars().all())

    # ==========================================================
    # Get By Category
    # ==========================================================

    async def get_by_category(
        self,
        category: str,
        limit: int = 10,
    ) -> list[Product]:

        result = await self.db.execute(
            select(Product)
            .where(
                Product.is_active.is_(True),
                Product.category == category,
            )
            .order_by(Product.sort_order.asc())
            .limit(limit)
        )

        return list(result.scalars().all())

    async def _resolve_category_id(self, category_id: str | None, legacy_cat: str | None) -> str | None:
        from app.models.category import Category
        val = category_id or legacy_cat
        if not val:
            return None

        # 1. Direct ID match
        res_id = await self.db.execute(select(Category.id).where(Category.id == val))
        matched_id = res_id.scalar_one_or_none()
        if matched_id:
            return matched_id

        # 2. Exact match on slug or name
        clean_val = val.strip()
        res_exact = await self.db.execute(
            select(Category.id).where(
                or_(
                    Category.slug == clean_val.lower(),
                    Category.name.ilike(clean_val)
                )
            ).order_by(Category.sort_order.asc())
        )
        matched_exact = res_exact.scalars().first()
        if matched_exact:
            return matched_exact

        # 3. Partial match on slug or name
        res_partial = await self.db.execute(
            select(Category.id).where(
                or_(
                    Category.slug.ilike(f"%{clean_val}%"),
                    Category.name.ilike(f"%{clean_val}%")
                )
            ).order_by(Category.sort_order.asc())
        )
        matched_partial = res_partial.scalars().first()
        if matched_partial:
            return matched_partial

        # 4. Fallback: Return first active category ID in database
        res_first = await self.db.execute(
            select(Category.id).where(Category.is_active.is_(True)).order_by(Category.sort_order.asc())
        )
        first_cat = res_first.scalars().first()
        return first_cat if first_cat else val

    # ==========================================================
    # Create
    # ==========================================================

    async def create(self, **kwargs) -> Product:
        category_id = kwargs.pop("category_id", None)
        legacy_cat = kwargs.pop("category", None)

        resolved_cat_id = await self._resolve_category_id(category_id, legacy_cat)

        product = Product(category_id=resolved_cat_id, **kwargs)
        self.db.add(product)
        await self.db.commit()
        await self.db.refresh(product)
        return product

    # ==========================================================
    # Update
    # ==========================================================

    async def update(
        self,
        product_id: str,
        commit: bool = True,
        **kwargs,
    ) -> Product | None:
        category_id = kwargs.pop("category_id", None)
        legacy_cat = kwargs.pop("category", None)

        if category_id is not None or legacy_cat is not None:
            resolved_cat_id = await self._resolve_category_id(category_id, legacy_cat)
            if resolved_cat_id:
                kwargs["category_id"] = resolved_cat_id

        if kwargs:
            await self.db.execute(
                update(Product)
                .where(Product.id == product_id)
                .values(**kwargs)
            )

        if commit:
            await self.db.commit()
        else:
            await self.db.flush()

        return await self.get_by_id(product_id)

    async def deduct_stock_atomic(self, product_id: str, quantity: int, commit: bool = True) -> bool:
        """
        Atomically deduct stock for a product if stock >= quantity.
        Returns True if successful, False if stock is insufficient.
        """
        stmt = (
            update(Product)
            .where(Product.id == product_id, Product.stock >= quantity)
            .values(stock=Product.stock - quantity)
        )
        res = await self.db.execute(stmt)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        return res.rowcount > 0

    # ==========================================================
    # Order Dependency & Summary
    # ==========================================================

    async def get_product_order_summary(self, product_id: str) -> dict:
        from app.models.order import Order, OrderItem

        active_statuses = [
            "Pending", "PENDING",
            "Confirmed", "CONFIRMED",
            "Processing", "PROCESSING",
            "Shipped", "SHIPPED",
            "Out for Delivery", "OUT_FOR_DELIVERY", "Out_For_Delivery",
        ]

        stmt = (
            select(Order.id, Order.status, func.coalesce(OrderItem.quantity, 1))
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(OrderItem.product_id == product_id)
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        total_orders = len(rows)
        active_order_ids: list[str] = []
        completed_orders = 0

        for order_id, order_status, _qty in rows:
            st = (order_status or "").strip()
            if any(st.lower() == act.lower() for act in active_statuses):
                active_order_ids.append(order_id)
            else:
                completed_orders += 1

        active_orders = len(active_order_ids)
        can_delete = (active_orders == 0)

        existing = await self.get_by_id(product_id)
        prod_name = existing.name if existing else "Product"

        return {
            "product_id": product_id,
            "product_name": prod_name,
            "total_orders": total_orders,
            "active_orders": active_orders,
            "completed_orders": completed_orders,
            "can_delete": can_delete,
            "active_order_ids": active_order_ids,
        }

    # ==========================================================
    # Delete
    # ==========================================================

    async def delete(self, product_id: str) -> None:
        from app.models.cart import CartItem
        from app.models.wishlist import WishlistItem
        from app.models.review import ProductReview
        from app.models.coupon import CouponProduct
        from app.models.order import OrderItem

        existing = await self.get_by_id(product_id)
        prod_name = existing.name if existing else "Archived Product"

        # 1. Preserve historical order items by storing product_name snapshot and decoupling product_id
        await self.db.execute(
            update(OrderItem)
            .where(OrderItem.product_id == product_id)
            .values(
                product_name=func.coalesce(OrderItem.product_name, prod_name),
                product_id=None
            )
        )

        # 2. Clean up child records in cart, wishlist, reviews, coupons
        await self.db.execute(delete(CartItem).where(CartItem.product_id == product_id))
        await self.db.execute(delete(WishlistItem).where(WishlistItem.product_id == product_id))
        await self.db.execute(delete(ProductReview).where(ProductReview.product_id == product_id))
        await self.db.execute(delete(CouponProduct).where(CouponProduct.product_id == product_id))

        # 3. Delete product permanently
        await self.db.execute(delete(Product).where(Product.id == product_id))
        await self.db.commit()

    # ==========================================================
    # Count
    # ==========================================================

    async def count(self) -> int:

        result = await self.db.execute(
            select(func.count()).select_from(Product)
        )

        return result.scalar() or 0
