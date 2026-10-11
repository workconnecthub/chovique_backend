from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.superadmin_theme import (
    ThemeCreateRequest,
    ThemeUpdateRequest,
    ThemeResponse,
    ThemeListResponse,
)
from app.services.superadmin_theme_service import SuperadminThemeService

router = APIRouter(prefix="/superadmin/themes", tags=["Superadmin Theme Builder"])


@router.get(
    "",
    response_model=ThemeListResponse,
    summary="Get all theme configurations",
)
async def get_all_themes(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.get_all_themes()


@router.get(
    "/active",
    response_model=ThemeResponse,
    summary="Get currently active theme configuration",
)
async def get_active_theme(
    db: AsyncSession = Depends(get_db),
):
    service = SuperadminThemeService(db)
    return await service.get_active_theme()


@router.get(
    "/{theme_id}",
    response_model=ThemeResponse,
    summary="Get theme configuration by ID",
)
async def get_theme_by_id(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.get_theme_by_id(theme_id)


@router.post(
    "",
    response_model=ThemeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom theme preset",
)
async def create_custom_theme(
    payload: ThemeCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.create_theme(payload, current_user)


@router.put(
    "/{theme_id}",
    response_model=ThemeResponse,
    summary="Update custom theme preset",
)
async def update_custom_theme(
    theme_id: str,
    payload: ThemeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.update_theme(theme_id, payload, current_user)


@router.post(
    "/{theme_id}/preview",
    response_model=ThemeResponse,
    summary="Preview theme configuration",
)
async def preview_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.preview_theme(theme_id, current_user)


@router.post(
    "/{theme_id}/apply",
    response_model=ThemeResponse,
    summary="Make selected theme active globally",
)
async def apply_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.apply_theme(theme_id, current_user)


@router.post(
    "/reset",
    response_model=ThemeResponse,
    summary="Restore Chovique Classic as active theme",
)
async def reset_theme(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.reset_theme(current_user)


@router.delete(
    "/{theme_id}",
    summary="Delete custom theme preset",
)
async def delete_theme(
    theme_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("superadmin")),
):
    service = SuperadminThemeService(db)
    return await service.delete_theme(theme_id, current_user)
