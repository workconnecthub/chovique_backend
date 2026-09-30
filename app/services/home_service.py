import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.product_repository import ProductRepository
from app.repositories.banner_repository import BannerRepository
from app.repositories.testimonial_repository import TestimonialRepository
from app.repositories.site_config_repository import SiteConfigRepository

from app.schemas.home import (
    BannerResponse,
    ContactInfoResponse,
    HomePageResponse,
    StatsResponse,
    TestimonialResponse,
)
from app.schemas.product import ProductResponse

logger = logging.getLogger(__name__)


class HomeService:

    def __init__(self, db: AsyncSession):
        self.db = db
        self.product_repo = ProductRepository(db)
        self.banner_repo = BannerRepository(db)
        self.testimonial_repo = TestimonialRepository(db)
        self.config_repo = SiteConfigRepository(db)

    # ==========================================================
    # Get Full Home Page Data (Single Optimized Call)
    # ==========================================================

    async def get_home_page_data(self) -> HomePageResponse:
        """
        Aggregates all landing page data in a single service call
        to minimize frontend requests.
        """

        logger.info("Fetching home page data")

        # Fetch all data concurrently would be ideal, but since
        # we share the same db session, we execute sequentially
        # to avoid session conflicts.

        from app.repositories.category_repository import CategoryRepository
        from app.repositories.faq_repository import FAQRepository
        from app.schemas.category import CategoryResponse
        from app.schemas.faq import FAQResponse

        category_repo = CategoryRepository(self.db)
        faq_repo = FAQRepository(self.db)

        banners = await self.banner_repo.get_active()
        categories = await category_repo.get_all()
        featured = await self.product_repo.get_featured(limit=4)
        bestsellers = await self.product_repo.get_bestsellers(limit=4)
        new_arrivals = await self.product_repo.get_new_arrivals(limit=4)
        testimonials = await self.testimonial_repo.get_active()
        faqs = await faq_repo.get_active_faqs()

        # Get site config data
        config_data = await self.config_repo.get_many([
            "stats",
            "contact",
        ])

        # Build stats
        stats_data = config_data.get("stats", {})
        happy_cust = stats_data.get("happy_customers", 50000)
        prod_avail = stats_data.get("products_available", stats_data.get("unique_flavors", 120))
        orders_deliv = stats_data.get("orders_delivered", stats_data.get("countries_shipped", 1500))
        rating_pct = stats_data.get("customer_rating_percent", stats_data.get("five_star_reviews_percent", 98))

        stats = StatsResponse(
            happy_customers=happy_cust,
            products_available=prod_avail,
            orders_delivered=orders_deliv,
            customer_rating_percent=rating_pct,
            unique_flavors=prod_avail,
            countries_shipped=orders_deliv,
            five_star_reviews_percent=rating_pct,
        )

        # Build contact
        contact_data = config_data.get("contact", {})
        contact = ContactInfoResponse(
            email=contact_data.get("email", ""),
            phone=contact_data.get("phone", ""),
            address=contact_data.get("address", ""),
            instagram=contact_data.get("instagram", ""),
            facebook=contact_data.get("facebook", ""),
            twitter=contact_data.get("twitter", ""),
        )

        return HomePageResponse(
            banners=[
                BannerResponse.from_orm_model(b) for b in banners
            ],
            categories=[
                CategoryResponse.model_validate(c) for c in categories
            ],
            featured_products=[
                ProductResponse.from_orm_model(p) for p in featured
            ],
            bestsellers=[
                ProductResponse.from_orm_model(p) for p in bestsellers
            ],
            new_arrivals=[
                ProductResponse.from_orm_model(p) for p in new_arrivals
            ],
            testimonials=[
                TestimonialResponse.from_orm_model(t) for t in testimonials
            ],
            faqs=[
                FAQResponse.model_validate(f) for f in faqs
            ],
            stats=stats,
            contact=contact,
        )

    # ==========================================================
    # Get Banners
    # ==========================================================

    async def get_banners(self) -> list[BannerResponse]:

        banners = await self.banner_repo.get_active()

        return [
            BannerResponse.from_orm_model(b) for b in banners
        ]

    # ==========================================================
    # Get Testimonials (Approved Only for Public Display)
    # ==========================================================

    async def get_testimonials(self) -> list[TestimonialResponse]:
        testimonials = await self.testimonial_repo.get_active()
        resp_list = [
            TestimonialResponse.from_orm_model(t) for t in testimonials
        ]

        try:
            from app.repositories.review_repository import ReviewRepository
            review_repo = ReviewRepository(self.db)
            featured_reviews = await review_repo.get_featured_on_home(limit=10)
            for r in featured_reviews:
                prod_name = r.product.name if r.product else "Artisanal Chocolate"
                initials = "".join([w[0].upper() for w in r.author.split()[:2]]) if r.author else "CL"
                avatar = r.images[0] if (r.images and len(r.images) > 0) else None
                title_str = f"Verified Buyer • {prod_name}"
                if not any(t.author == r.author and t.text == r.text for t in resp_list):
                    resp_list.insert(0, TestimonialResponse(
                        id=f"feat-{r.id}",
                        author=r.author,
                        title=title_str,
                        text=f'"{r.title}" — {r.text}' if r.title else r.text,
                        rating=r.rating,
                        stars=int(round(r.rating)),
                        initials=initials,
                        avatar_url=avatar,
                        status="approved",
                        is_active=True,
                        sort_order=0,
                    ))
        except Exception:
            pass

        return resp_list

    async def submit_testimonial(
        self,
        author: str,
        text: str,
        title: str | None = None,
        rating: float = 5.0,
        user_id: str | None = None,
        avatar_url: str | None = None,
    ) -> TestimonialResponse:
        initials = "".join([w[0].upper() for w in author.split()[:2]]) if author else "U"
        testimonial = await self.testimonial_repo.create(
            user_id=user_id,
            author=author,
            title=title or "Chocolate Enthusiast",
            text=text,
            rating=rating,
            initials=initials,
            avatar_url=avatar_url,
            status="pending",
            is_active=False,
        )
        return TestimonialResponse.from_orm_model(testimonial)

    # ==========================================================
    # Get Theme
    # ==========================================================

    async def get_theme(self) -> dict | list | str | None:
        return await self.config_repo.get("theme")

    # ==========================================================
    # Get Stats
    # ==========================================================

    async def get_stats(self) -> StatsResponse:

        stats_data = await self.config_repo.get("stats")

        if not stats_data or not isinstance(stats_data, dict):
            return StatsResponse()

        happy_cust = stats_data.get("happy_customers", 50000)
        prod_avail = stats_data.get("products_available", stats_data.get("unique_flavors", 120))
        orders_deliv = stats_data.get("orders_delivered", stats_data.get("countries_shipped", 1500))
        rating_pct = stats_data.get("customer_rating_percent", stats_data.get("five_star_reviews_percent", 98))

        return StatsResponse(
            happy_customers=happy_cust,
            products_available=prod_avail,
            orders_delivered=orders_deliv,
            customer_rating_percent=rating_pct,
            unique_flavors=prod_avail,
            countries_shipped=orders_deliv,
            five_star_reviews_percent=rating_pct,
        )

    # ==========================================================
    # Get Contact Info
    # ==========================================================

    async def get_contact(self) -> ContactInfoResponse:
        contact_data = await self.config_repo.get("contact")

        if not contact_data or not isinstance(contact_data, dict):
            return ContactInfoResponse()

        return ContactInfoResponse(
            email=contact_data.get("email", "support@chovique.com"),
            phone=contact_data.get("phone", "+91 83098 54870"),
            whatsapp=contact_data.get("whatsapp", "+91 83098 54870"),
            support_hours=contact_data.get("support_hours", "Mon - Sat: 10:00 AM - 8:00 PM | Sunday: 11:00 AM - 6:00 PM"),
            address=contact_data.get("address", "42, MG Road, Indiranagar, Bangalore, Karnataka 560038"),
            instagram=contact_data.get("instagram", "https://instagram.com"),
            facebook=contact_data.get("facebook", "https://facebook.com"),
            twitter=contact_data.get("twitter", "https://x.com"),
        )

    async def get_reels(self):
        from app.repositories.reel_repository import ReelRepository
        repo = ReelRepository(self.db)
        reels = await repo.get_active_reels()
        return [
            {
                "id": r.id,
                "videoUrl": r.video_url,
                "instagramUrl": r.instagram_url,
                "accountName": r.account_name or "@chovique_chocolatier",
                "likes": r.likes,
                "comments": r.comments,
                "views": r.views,
                "title": r.title,
            }
            for r in reels
        ]
