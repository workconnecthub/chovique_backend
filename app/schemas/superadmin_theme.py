import re
from typing import Optional, List
from pydantic import BaseModel, Field, validator

HEX_COLOR_REGEX = re.compile(r"^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")


class ThemeColors(BaseModel):
    # Core Colors
    primary_brand_color: str = Field(..., example="#5A3825")
    background_color: str = Field(..., example="#0D090A")
    luxury_gold_color: str = Field(..., example="#D4AF37")
    secondary_accent_color: str = Field(..., example="#B76E79")
    text_color: str = Field(..., example="#F7F7F7")
    surface_color: str = Field(..., example="#1A1716")

    # Granular Component Colors
    button_color: Optional[str] = Field(default="#5A3825", example="#5A3825")
    button_text_color: Optional[str] = Field(default="#FFFFFF", example="#FFFFFF")
    secondary_button_color: Optional[str] = Field(default="#D4AF37", example="#D4AF37")
    cart_color: Optional[str] = Field(default="#D4AF37", example="#D4AF37")
    cart_text_color: Optional[str] = Field(default="#0D090A", example="#0D090A")
    product_card_color: Optional[str] = Field(default="#1A1716", example="#1A1716")
    product_card_border_color: Optional[str] = Field(default="#D4AF37", example="#D4AF37")
    product_card_text_color: Optional[str] = Field(default="#F7F7F7", example="#F7F7F7")
    navbar_color: Optional[str] = Field(default="#0D090A", example="#0D090A")
    navbar_text_color: Optional[str] = Field(default="#F7F7F7", example="#F7F7F7")
    footer_color: Optional[str] = Field(default="#0A0A0A", example="#0A0A0A")
    footer_text_color: Optional[str] = Field(default="#F7F7F7", example="#F7F7F7")

    # Typography & Number Fonts
    font_family: Optional[str] = Field(default="Outfit", example="Outfit")
    heading_font_family: Optional[str] = Field(default="Playfair Display", example="Playfair Display")
    number_font_family: Optional[str] = Field(default="Outfit", example="Outfit")

    @validator(
        "primary_brand_color",
        "background_color",
        "luxury_gold_color",
        "secondary_accent_color",
        "text_color",
        "surface_color",
        "button_color",
        "button_text_color",
        "secondary_button_color",
        "cart_color",
        "cart_text_color",
        "product_card_color",
        "product_card_border_color",
        "product_card_text_color",
        "navbar_color",
        "navbar_text_color",
        "footer_color",
        "footer_text_color",
        pre=True,
    )
    def validate_hex_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not isinstance(v, str):
            raise ValueError("Color value must be a string.")
        v_clean = v.strip()
        if not v_clean:
            return None
        if not HEX_COLOR_REGEX.match(v_clean):
            raise ValueError(f"Invalid HEX color format: '{v_clean}'. Expected #RRGGBB format.")
        return v_clean.upper()


class ThemeCreateRequest(ThemeColors):
    name: str = Field(..., min_length=2, max_length=120, example="Custom Gold Luxury")
    description: Optional[str] = Field(None, example="Custom theme palette created by Superadmin")


class ThemeUpdateRequest(ThemeColors):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    description: Optional[str] = None


class ThemeResponse(ThemeColors):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool = False
    is_preset: bool = False
    created_at: str
    updated_at: str
    created_by: Optional[str] = None


class ThemeListResponse(BaseModel):
    items: List[ThemeResponse] = Field(default_factory=list)
    active_theme_id: Optional[str] = None
