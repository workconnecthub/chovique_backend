from typing import Optional
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.db.session import get_db
from app.models.user import User
from app.services.home_service import HomeService
from app.services.platform_settings_service import PlatformSettingsService
from app.schemas.home import (
    BannerResponse,
    ContactInfoResponse,
    HomePageResponse,
    StatsResponse,
    TestimonialResponse,
    StoreConfigResponse,
)

router = APIRouter(prefix="/home", tags=["Home Page"])


class CreateCustomerTestimonialPayload(BaseModel):
    author: str
    text: str
    title: Optional[str] = None
    rating: float = Field(default=5.0, ge=1, le=5)


# ======================================================
# GET HOME PAGE DATA (AGGREGATED)
# ======================================================

@router.get(
    "",
    response_model=HomePageResponse,
    summary="Get aggregated home page data",
)
async def get_home_page(
    db: AsyncSession = Depends(get_db),
):
    """
    Returns all data needed for the landing page in a single call:
    banners, featured products, bestsellers, new arrivals,
    testimonials, stats, and contact info.
    """

    service = HomeService(db)
    return await service.get_home_page_data()


# ======================================================
# GET STORE CONFIG
# ======================================================

@router.get(
    "/store-config",
    response_model=StoreConfigResponse,
    summary="Get public store configuration",
)
async def get_store_config(
    db: AsyncSession = Depends(get_db),
):
    """
    Returns public-facing store configuration for dynamic
    shipping, tax, and order calculations on the frontend.
    """
    service = PlatformSettingsService(db)
    settings = await service.get_settings()
    
    return StoreConfigResponse(
        standard_shipping_charge=settings.standard_shipping_charge,
        free_shipping_min_order=settings.free_shipping_min_order,
        gst_rate=settings.gst_rate,
        cod_enabled=settings.cod_enabled,
        minimum_order_value=settings.minimum_order_value,
        maximum_cod_order_value=settings.maximum_cod_order_value,
        base_currency=settings.base_currency,
        store_front_name=settings.store_front_name,
    )


# ======================================================
# GET BANNERS
# ======================================================

@router.get(
    "/banners",
    response_model=list[BannerResponse],
    summary="Get active banners",
)
async def get_banners(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_banners()


# ======================================================
# TESTIMONIALS (Public GET approved / Customer POST submit)
# ======================================================

@router.get(
    "/testimonials",
    response_model=list[TestimonialResponse],
    summary="Get testimonials",
)
async def get_testimonials(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_testimonials()


@router.post(
    "/testimonials",
    response_model=TestimonialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit brand testimonial (pending admin approval)",
)
async def submit_testimonial(
    payload: CreateCustomerTestimonialPayload,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    user_id = current_user.id if current_user else None
    return await service.submit_testimonial(
        author=payload.author,
        text=payload.text,
        title=payload.title,
        rating=payload.rating,
        user_id=user_id,
    )


# ======================================================
# GET STATS
# ======================================================

@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Get site stats",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_stats()


# ======================================================
# GET CONTACT INFO
# ======================================================

@router.get(
    "/contact",
    response_model=ContactInfoResponse,
    summary="Get contact information",
)
async def get_contact(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_contact()


@router.get(
    "/theme",
    summary="Get global theme configuration",
)
async def get_theme(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    theme = await service.get_theme()
    return theme if theme else {}


@router.get(
    "/reels",
    summary="Get active Instagram reels",
)
async def get_reels(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_reels()


@router.get(
    "/story-video",
    summary="Get Our Story crafting process video URL",
)
async def get_story_video(
    db: AsyncSession = Depends(get_db),
):
    from app.services.admin_service import AdminService
    service = AdminService(db)
    url = await service.get_story_video()
    return {"video_url": url}


# ======================================================
# GET LANDING PAGE CUSTOMIZABLE SECTIONS
# ======================================================

@router.get(
    "/landing-sections",
    summary="Get public landing page customizable sections configuration",
)
async def get_landing_sections(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_landing_sections()


@router.get(
    "/story-page",
    summary="Get Our Story page content and process configuration",
)
async def get_story_page(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_story_page_config()


@router.get(
    "/contact-page",
    summary="Get Contact Us page details and channel configuration",
)
async def get_contact_page(
    db: AsyncSession = Depends(get_db),
):
    service = HomeService(db)
    return await service.get_contact_page_config()



