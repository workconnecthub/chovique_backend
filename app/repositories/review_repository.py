from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.review import ProductReview


class ReviewRepository:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_product_reviews(self, product_id: str, status: str = "approved") -> list[ProductReview]:
        query = (
            select(ProductReview)
            .where(ProductReview.product_id == product_id)
        )
        if status:
            query = query.where(ProductReview.status == status)
        query = query.order_by(ProductReview.created_at.desc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, review_id: str) -> ProductReview | None:
        result = await self.db.execute(
            select(ProductReview).where(ProductReview.id == review_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> ProductReview:
        review = ProductReview(**kwargs)
        self.db.add(review)
        await self.db.commit()
        await self.db.refresh(review)
        return review

    async def delete(self, review_id: str) -> bool:
        result = await self.db.execute(
            delete(ProductReview).where(ProductReview.id == review_id)
        )
        await self.db.commit()
        return result.rowcount > 0

    async def update_status(self, review_id: str, status: str, is_featured_on_home: bool | None = None) -> ProductReview | None:
        review = await self.get_by_id(review_id)
        if not review:
            return None
        review.status = status
        if is_featured_on_home is not None:
            review.is_featured_on_home = is_featured_on_home
        await self.db.commit()
        await self.db.refresh(review)
        return review

    async def get_featured_on_home(self, limit: int = 10) -> list[ProductReview]:
        from sqlalchemy.orm import joinedload
        result = await self.db.execute(
            select(ProductReview)
            .options(joinedload(ProductReview.product))
            .where(ProductReview.status == "approved", ProductReview.is_featured_on_home == True)
            .order_by(ProductReview.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_all(self, limit: int = 100) -> list[ProductReview]:
        from sqlalchemy.orm import joinedload
        result = await self.db.execute(
            select(ProductReview)
            .options(joinedload(ProductReview.product))
            .order_by(ProductReview.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def user_has_reviewed_product(self, user_id: str, product_id: str) -> bool:
        if not user_id:
            return False
        result = await self.db.execute(
            select(func.count())
            .select_from(ProductReview)
            .where(ProductReview.user_id == user_id, ProductReview.product_id == product_id)
        )
        return (result.scalar() or 0) > 0

    async def get_rating_summary(self, product_id: str) -> dict:
        """
        Calculate average rating, count, and star breakdown (1 to 5 stars)
        for approved product reviews.
        """
        reviews = await self.get_product_reviews(product_id, status="approved")
        total_count = len(reviews)
        if total_count == 0:
            return {
                "average_rating": 0.0,
                "total_reviews": 0,
                "star_breakdown": {5: 0, 4: 0, 3: 0, 2: 0, 1: 0},
            }

        total_sum = sum(r.rating for r in reviews)
        avg_rating = round(total_sum / total_count, 1)

        breakdown = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
        for r in reviews:
            star = int(round(r.rating))
            star = max(1, min(5, star))
            breakdown[star] += 1

        return {
            "average_rating": avg_rating,
            "total_reviews": total_count,
            "star_breakdown": breakdown,
        }

    async def count(self) -> int:
        result = await self.db.execute(select(func.count()).select_from(ProductReview))
        return result.scalar() or 0
