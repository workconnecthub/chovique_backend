import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.theme import ThemePreset
from app.models.user import User
from app.schemas.superadmin_theme import (
    ThemeCreateRequest,
    ThemeUpdateRequest,
    ThemeResponse,
    ThemeListResponse,
)
from app.services.superadmin_audit_logs_service import record_audit_event

PRESET_SEED_DATA = [
    {
        "id": "preset-chovique-classic",
        "name": "Chovique Classic",
        "description": "Signature chocolate & gold luxury palette with artisanal warmth",
        "primary_brand_color": "#5A3825",
        "background_color": "#0D090A",
        "luxury_gold_color": "#D4AF37",
        "secondary_accent_color": "#B76E79",
        "text_color": "#F7F7F7",
        "surface_color": "#1A1716",
        "button_color": "#5A3825",
        "button_text_color": "#FFFFFF",
        "secondary_button_color": "#D4AF37",
        "cart_color": "#D4AF37",
        "cart_text_color": "#0D090A",
        "product_card_color": "#1A1716",
        "product_card_border_color": "#D4AF37",
        "product_card_text_color": "#F7F7F7",
        "navbar_color": "#0D090A",
        "navbar_text_color": "#F7F7F7",
        "footer_color": "#0A0A0A",
        "footer_text_color": "#F7F7F7",
        "font_family": "Outfit",
        "heading_font_family": "Playfair Display",
        "number_font_family": "Outfit",
        "is_active": True,
        "is_preset": True,
    },
    {
        "id": "preset-slate-noir",
        "name": "Slate Noir",
        "description": "Sophisticated gradient from dark slate to charcoal gray with crisp accents",
        "primary_brand_color": "#2C3E50",
        "background_color": "#1A252F",
        "luxury_gold_color": "#BDC3C7",
        "secondary_accent_color": "#7F8C8D",
        "text_color": "#ECF0F1",
        "surface_color": "#2C3E50",
        "button_color": "#34495E",
        "button_text_color": "#FFFFFF",
        "secondary_button_color": "#BDC3C7",
        "cart_color": "#BDC3C7",
        "cart_text_color": "#1A252F",
        "product_card_color": "#243342",
        "product_card_border_color": "#34495E",
        "product_card_text_color": "#ECF0F1",
        "navbar_color": "#1A252F",
        "navbar_text_color": "#ECF0F1",
        "footer_color": "#141D26",
        "footer_text_color": "#BDC3C7",
        "font_family": "Inter",
        "heading_font_family": "Montserrat",
        "number_font_family": "Inter",
        "is_active": False,
        "is_preset": True,
    },
    {
        "id": "preset-dark-elegance",
        "name": "Dark Elegance",
        "description": "Deep velvet black with rich warm gold highlights and royal flair",
        "primary_brand_color": "#1E1B18",
        "background_color": "#080706",
        "luxury_gold_color": "#E6C687",
        "secondary_accent_color": "#8A734C",
        "text_color": "#F0E6D2",
        "surface_color": "#181512",
        "button_color": "#E6C687",
        "button_text_color": "#080706",
        "secondary_button_color": "#8A734C",
        "cart_color": "#E6C687",
        "cart_text_color": "#080706",
        "product_card_color": "#181512",
        "product_card_border_color": "#8A734C",
        "product_card_text_color": "#F0E6D2",
        "navbar_color": "#080706",
        "navbar_text_color": "#F0E6D2",
        "footer_color": "#050403",
        "footer_text_color": "#C4BAA9",
        "font_family": "Plus Jakarta Sans",
        "heading_font_family": "Playfair Display",
        "number_font_family": "Plus Jakarta Sans",
        "is_active": False,
        "is_preset": True,
    },
    {
        "id": "preset-midnight-premium",
        "name": "Midnight Premium",
        "description": "Deep navy with vivid cyan accents and monospaced numerical clarity",
        "primary_brand_color": "#0F172A",
        "background_color": "#020617",
        "luxury_gold_color": "#38BDF8",
        "secondary_accent_color": "#94A3B8",
        "text_color": "#F8FAFC",
        "surface_color": "#1E293B",
        "button_color": "#2563EB",
        "button_text_color": "#FFFFFF",
        "secondary_button_color": "#38BDF8",
        "cart_color": "#38BDF8",
        "cart_text_color": "#020617",
        "product_card_color": "#0F172A",
        "product_card_border_color": "#1E293B",
        "product_card_text_color": "#F8FAFC",
        "navbar_color": "#020617",
        "navbar_text_color": "#F8FAFC",
        "footer_color": "#01040D",
        "footer_text_color": "#94A3B8",
        "font_family": "Poppins",
        "heading_font_family": "Outfit",
        "number_font_family": "JetBrains Mono",
        "is_active": False,
        "is_preset": True,
    },
    {
        "id": "preset-royal-emerald",
        "name": "Royal Emerald",
        "description": "Deep imperial emerald green paired with radiant champagne gold",
        "primary_brand_color": "#064E3B",
        "background_color": "#022C22",
        "luxury_gold_color": "#FBBF24",
        "secondary_accent_color": "#10B981",
        "text_color": "#F0FDF4",
        "surface_color": "#065F46",
        "button_color": "#047857",
        "button_text_color": "#FFFFFF",
        "secondary_button_color": "#FBBF24",
        "cart_color": "#FBBF24",
        "cart_text_color": "#022C22",
        "product_card_color": "#064E3B",
        "product_card_border_color": "#047857",
        "product_card_text_color": "#F0FDF4",
        "navbar_color": "#022C22",
        "navbar_text_color": "#F0FDF4",
        "footer_color": "#011C15",
        "footer_text_color": "#A7F3D0",
        "font_family": "Outfit",
        "heading_font_family": "Cormorant Garamond",
        "number_font_family": "Space Grotesk",
        "is_active": False,
        "is_preset": True,
    },
    {
        "id": "preset-rose-champagne",
        "name": "Rose Champagne",
        "description": "Warm luxury blush, velvety dark cacao, and radiant rose gold accents",
        "primary_brand_color": "#4A1525",
        "background_color": "#1A0A10",
        "luxury_gold_color": "#F472B6",
        "secondary_accent_color": "#FB7185",
        "text_color": "#FFF1F2",
        "surface_color": "#2D0F1C",
        "button_color": "#BE185D",
        "button_text_color": "#FFFFFF",
        "secondary_button_color": "#F472B6",
        "cart_color": "#F472B6",
        "cart_text_color": "#1A0A10",
        "product_card_color": "#2D0F1C",
        "product_card_border_color": "#BE185D",
        "product_card_text_color": "#FFF1F2",
        "navbar_color": "#1A0A10",
        "navbar_text_color": "#FFF1F2",
        "footer_color": "#10050A",
        "footer_text_color": "#FDA4AF",
        "font_family": "Outfit",
        "heading_font_family": "Playfair Display",
        "number_font_family": "Outfit",
        "is_active": False,
        "is_preset": True,
    },
]


class SuperadminThemeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def seed_preset_themes(self):
        """Ensure all curated preset themes exist and are up to date in database."""
        for seed in PRESET_SEED_DATA:
            res = await self.db.execute(select(ThemePreset).where(ThemePreset.name == seed["name"]))
            existing = res.scalars().first()
            if not existing:
                theme = ThemePreset(
                    id=seed["id"],
                    name=seed["name"],
                    description=seed["description"],
                    primary_brand_color=seed["primary_brand_color"],
                    background_color=seed["background_color"],
                    luxury_gold_color=seed["luxury_gold_color"],
                    secondary_accent_color=seed["secondary_accent_color"],
                    text_color=seed["text_color"],
                    surface_color=seed["surface_color"],
                    button_color=seed["button_color"],
                    button_text_color=seed["button_text_color"],
                    secondary_button_color=seed["secondary_button_color"],
                    cart_color=seed["cart_color"],
                    cart_text_color=seed["cart_text_color"],
                    product_card_color=seed["product_card_color"],
                    product_card_border_color=seed["product_card_border_color"],
                    product_card_text_color=seed["product_card_text_color"],
                    navbar_color=seed["navbar_color"],
                    navbar_text_color=seed["navbar_text_color"],
                    footer_color=seed["footer_color"],
                    footer_text_color=seed["footer_text_color"],
                    font_family=seed["font_family"],
                    heading_font_family=seed["heading_font_family"],
                    number_font_family=seed["number_font_family"],
                    properties_json="{}",
                    is_active=seed["is_active"],
                    is_preset=seed["is_preset"],
                )
                self.db.add(theme)
            elif existing.is_preset:
                # Update preset defaults ONLY if column value is missing or null
                for key, val in seed.items():
                    if hasattr(existing, key) and key not in ("id", "is_active", "name"):
                        current_val = getattr(existing, key)
                        if current_val is None or current_val == "":
                            setattr(existing, key, val)
        await self.db.commit()

    def _to_response(self, theme: ThemePreset) -> ThemeResponse:
        created_str = theme.created_at.strftime("%Y-%m-%d %H:%M:%S") if theme.created_at else ""
        updated_str = theme.updated_at.strftime("%Y-%m-%d %H:%M:%S") if theme.updated_at else ""
        return ThemeResponse(
            id=theme.id,
            name=theme.name,
            description=theme.description,
            primary_brand_color=theme.primary_brand_color or "#5A3825",
            background_color=theme.background_color or "#0D090A",
            luxury_gold_color=theme.luxury_gold_color or "#D4AF37",
            secondary_accent_color=theme.secondary_accent_color or "#B76E79",
            text_color=theme.text_color or "#F7F7F7",
            surface_color=theme.surface_color or "#1A1716",
            button_color=getattr(theme, "button_color", None) or theme.primary_brand_color or "#5A3825",
            button_text_color=getattr(theme, "button_text_color", None) or "#FFFFFF",
            secondary_button_color=getattr(theme, "secondary_button_color", None) or theme.luxury_gold_color or "#D4AF37",
            cart_color=getattr(theme, "cart_color", None) or theme.luxury_gold_color or "#D4AF37",
            cart_text_color=getattr(theme, "cart_text_color", None) or theme.background_color or "#0D090A",
            product_card_color=getattr(theme, "product_card_color", None) or theme.surface_color or "#1A1716",
            product_card_border_color=getattr(theme, "product_card_border_color", None) or theme.luxury_gold_color or "#D4AF37",
            product_card_text_color=getattr(theme, "product_card_text_color", None) or theme.text_color or "#F7F7F7",
            navbar_color=getattr(theme, "navbar_color", None) or theme.background_color or "#0D090A",
            navbar_text_color=getattr(theme, "navbar_text_color", None) or theme.text_color or "#F7F7F7",
            footer_color=getattr(theme, "footer_color", None) or "#0A0A0A",
            footer_text_color=getattr(theme, "footer_text_color", None) or theme.text_color or "#F7F7F7",
            font_family=getattr(theme, "font_family", None) or "Outfit",
            heading_font_family=getattr(theme, "heading_font_family", None) or "Playfair Display",
            number_font_family=getattr(theme, "number_font_family", None) or "Outfit",
            is_active=theme.is_active,
            is_preset=theme.is_preset,
            created_at=created_str,
            updated_at=updated_str,
            created_by=theme.created_by,
        )

    async def get_all_themes(self) -> ThemeListResponse:
        await self.seed_preset_themes()
        res = await self.db.execute(select(ThemePreset).order_by(ThemePreset.is_preset.desc(), ThemePreset.created_at.asc()))
        themes = res.scalars().all()
        active_id = next((t.id for t in themes if t.is_active), None)
        return ThemeListResponse(
            items=[self._to_response(t) for t in themes],
            active_theme_id=active_id,
        )

    async def get_active_theme(self) -> ThemeResponse:
        """Get currently active theme configuration, or fallback to Chovique Classic."""
        await self.seed_preset_themes()
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.is_active == True))
        theme = res.scalars().first()
        if not theme:
            res_default = await self.db.execute(select(ThemePreset).where(ThemePreset.name == "Chovique Classic"))
            theme = res_default.scalars().first()
        if not theme:
            res_first = await self.db.execute(select(ThemePreset).limit(1))
            theme = res_first.scalars().first()
        if not theme:
            raise HTTPException(status_code=404, detail="No active theme found.")
        return self._to_response(theme)

    async def get_theme_by_id(self, theme_id: str) -> ThemeResponse:
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.id == theme_id))
        theme = res.scalars().first()
        if not theme:
            raise HTTPException(status_code=404, detail="Theme preset not found.")
        return self._to_response(theme)

    async def create_theme(self, payload: ThemeCreateRequest, current_user: User) -> ThemeResponse:
        # Check duplicate name
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.name == payload.name.strip()))
        if res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Theme name '{payload.name}' already exists. Please choose a unique name.",
            )

        theme = ThemePreset(
            id=str(uuid.uuid4()),
            name=payload.name.strip(),
            description=payload.description.strip() if payload.description else None,
            primary_brand_color=payload.primary_brand_color,
            background_color=payload.background_color,
            luxury_gold_color=payload.luxury_gold_color,
            secondary_accent_color=payload.secondary_accent_color,
            text_color=payload.text_color,
            surface_color=payload.surface_color,
            button_color=payload.button_color or payload.primary_brand_color,
            button_text_color=payload.button_text_color or "#FFFFFF",
            secondary_button_color=payload.secondary_button_color or payload.luxury_gold_color,
            cart_color=payload.cart_color or payload.luxury_gold_color,
            cart_text_color=payload.cart_text_color or payload.background_color,
            product_card_color=payload.product_card_color or payload.surface_color,
            product_card_border_color=payload.product_card_border_color or payload.luxury_gold_color,
            product_card_text_color=payload.product_card_text_color or payload.text_color,
            navbar_color=payload.navbar_color or payload.background_color,
            navbar_text_color=payload.navbar_text_color or payload.text_color,
            footer_color=payload.footer_color or "#0A0A0A",
            footer_text_color=payload.footer_text_color or payload.text_color,
            font_family=payload.font_family or "Outfit",
            heading_font_family=payload.heading_font_family or "Playfair Display",
            number_font_family=payload.number_font_family or "Outfit",
            properties_json="{}",
            is_active=False,
            is_preset=False,
            created_by=current_user.id,
        )
        self.db.add(theme)
        await self.db.commit()
        await self.db.refresh(theme)

        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_CREATED",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=theme.id,
            metadata={"theme_name": theme.name},
        )
        await self.db.commit()

        return self._to_response(theme)

    async def update_theme(self, theme_id: str, payload: ThemeUpdateRequest, current_user: User) -> ThemeResponse:
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.id == theme_id))
        theme = res.scalars().first()
        if not theme:
            raise HTTPException(status_code=404, detail="Theme preset not found.")

        if payload.name and payload.name.strip() != theme.name:
            dup_res = await self.db.execute(select(ThemePreset).where(ThemePreset.name == payload.name.strip(), ThemePreset.id != theme_id))
            if dup_res.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Theme name '{payload.name}' already exists.",
                )
            theme.name = payload.name.strip()

        if payload.description is not None:
            theme.description = payload.description.strip()

        theme.primary_brand_color = payload.primary_brand_color
        theme.background_color = payload.background_color
        theme.luxury_gold_color = payload.luxury_gold_color
        theme.secondary_accent_color = payload.secondary_accent_color
        theme.text_color = payload.text_color
        theme.surface_color = payload.surface_color
        
        if payload.button_color is not None:
            theme.button_color = payload.button_color
        if payload.button_text_color is not None:
            theme.button_text_color = payload.button_text_color
        if payload.secondary_button_color is not None:
            theme.secondary_button_color = payload.secondary_button_color
        if payload.cart_color is not None:
            theme.cart_color = payload.cart_color
        if payload.cart_text_color is not None:
            theme.cart_text_color = payload.cart_text_color
        if payload.product_card_color is not None:
            theme.product_card_color = payload.product_card_color
        if payload.product_card_border_color is not None:
            theme.product_card_border_color = payload.product_card_border_color
        if payload.product_card_text_color is not None:
            theme.product_card_text_color = payload.product_card_text_color
        if payload.navbar_color is not None:
            theme.navbar_color = payload.navbar_color
        if payload.navbar_text_color is not None:
            theme.navbar_text_color = payload.navbar_text_color
        if payload.footer_color is not None:
            theme.footer_color = payload.footer_color
        if payload.footer_text_color is not None:
            theme.footer_text_color = payload.footer_text_color
        if payload.font_family is not None:
            theme.font_family = payload.font_family
        if payload.heading_font_family is not None:
            theme.heading_font_family = payload.heading_font_family
        if payload.number_font_family is not None:
            theme.number_font_family = payload.number_font_family

        await self.db.commit()
        await self.db.refresh(theme)

        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_UPDATED",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=theme.id,
            metadata={"theme_name": theme.name},
        )
        await self.db.commit()

        return self._to_response(theme)

    async def preview_theme(self, theme_id: str, current_user: User) -> ThemeResponse:
        theme = await self.get_theme_by_id(theme_id)
        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_PREVIEWED",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=theme.id,
            metadata={"theme_name": theme.name},
        )
        await self.db.commit()
        return theme

    async def apply_theme(self, theme_id: str, current_user: User) -> ThemeResponse:
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.id == theme_id))
        target_theme = res.scalars().first()
        if not target_theme:
            raise HTTPException(status_code=404, detail="Theme preset not found.")

        # Deactivate all themes
        all_res = await self.db.execute(select(ThemePreset))
        all_themes = all_res.scalars().all()
        for t in all_themes:
            t.is_active = (t.id == theme_id)

        await self.db.commit()
        await self.db.refresh(target_theme)

        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_APPLIED",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=target_theme.id,
            metadata={"theme_name": target_theme.name},
        )
        await self.db.commit()

        return self._to_response(target_theme)

    async def reset_theme(self, current_user: User) -> ThemeResponse:
        for seed in PRESET_SEED_DATA:
            res = await self.db.execute(select(ThemePreset).where(ThemePreset.name == seed["name"]))
            existing = res.scalars().first()
            if existing:
                for key, val in seed.items():
                    if hasattr(existing, key) and key not in ("id",):
                        setattr(existing, key, val)

        classic_res = await self.db.execute(select(ThemePreset).where(ThemePreset.name == "Chovique Classic"))
        classic_theme = classic_res.scalars().first()

        all_res = await self.db.execute(select(ThemePreset))
        for t in all_res.scalars().all():
            t.is_active = (t.name == "Chovique Classic")

        await self.db.commit()
        if classic_theme:
            await self.db.refresh(classic_theme)

        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_RESET",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=classic_theme.id if classic_theme else "reset",
            metadata={"reset_to": "Chovique Classic"},
        )
        await self.db.commit()

        return self._to_response(classic_theme)

    async def delete_theme(self, theme_id: str, current_user: User) -> dict:
        res = await self.db.execute(select(ThemePreset).where(ThemePreset.id == theme_id))
        theme = res.scalars().first()
        if not theme:
            raise HTTPException(status_code=404, detail="Theme preset not found.")

        if theme.is_preset:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="System preset themes cannot be deleted.",
            )

        if theme.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Active theme cannot be deleted. Please switch to another active theme first.",
            )

        t_name = theme.name
        await self.db.delete(theme)
        await self.db.commit()

        # Audit event
        await record_audit_event(
            db=self.db,
            action="THEME_DELETED",
            module="theme_builder",
            user_id=current_user.id,
            user_role=current_user.role,
            entity_type="theme_preset",
            entity_id=theme_id,
            metadata={"deleted_theme_name": t_name},
        )
        await self.db.commit()

        return {"message": f"Theme '{t_name}' deleted successfully."}
