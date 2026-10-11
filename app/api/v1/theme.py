from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.api.deps import require_role
from app.schemas.theme import ThemePresetPayload, ThemePresetResponse
from app.schemas.superadmin_theme import ThemeResponse
from app.services.theme_service import ThemeService
from app.services.superadmin_theme_service import SuperadminThemeService

router = APIRouter()

@router.get(
    "/",
    response_model=list[ThemePresetResponse],
    summary="Get all theme presets"
)
async def get_all_themes(
    db: AsyncSession = Depends(get_db)
):
    service = ThemeService(db)
    return await service.get_all_themes()

@router.get(
    "/active",
    response_model=ThemeResponse,
    summary="Get active theme preset"
)
async def get_active_theme(
    db: AsyncSession = Depends(get_db)
):
    service = SuperadminThemeService(db)
    return await service.get_active_theme()

@router.post(
    "/",
    response_model=ThemePresetResponse,
    summary="Save a custom theme preset (superadmin only)"
)
async def save_theme(
    payload: ThemePresetPayload,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db)
):
    service = ThemeService(db)
    return await service.save_theme(payload)

@router.put(
    "/{theme_id}/active",
    summary="Set active theme (superadmin only)"
)
async def set_active_theme(
    theme_id: str,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db)
):
    service = ThemeService(db)
    success = await service.set_active_theme(theme_id)
    if not success:
        raise HTTPException(status_code=404, detail="Theme not found.")
    return {"message": "Theme activated successfully"}

@router.delete(
    "/{theme_id}",
    summary="Delete a custom theme preset (superadmin only)"
)
async def delete_theme(
    theme_id: str,
    current_user: User = Depends(require_role("superadmin")),
    db: AsyncSession = Depends(get_db)
):
    service = ThemeService(db)
    success = await service.delete_theme(theme_id)
    if not success:
        raise HTTPException(status_code=404, detail="Theme not found.")
    return {"message": "Theme deleted successfully"}
