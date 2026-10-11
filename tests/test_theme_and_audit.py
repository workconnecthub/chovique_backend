"""
Theme and Superadmin Audit Logs Endpoint Tests.

Covers:
- GET /api/v1/theme/active (public endpoint with seeds/fallback)
- GET /api/v1/superadmin/themes (list presets & themes)
- POST /api/v1/superadmin/themes (create custom theme with granular colors)
- PUT /api/v1/superadmin/themes/{theme_id} (update theme)
- POST /api/v1/superadmin/themes/{theme_id}/activate (activate theme)
- POST /api/v1/superadmin/themes/reset (reset theme to classic)
- DELETE /api/v1/superadmin/audit-logs/{log_id} (single delete)
- POST /api/v1/superadmin/audit-logs/bulk-delete (bulk delete)
"""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.services.superadmin_service import ensure_superadmin_exists
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _get_superadmin_client(client: AsyncClient) -> AsyncClient:
    async with TestSessionLocal() as session:
        await ensure_superadmin_exists(session)
        await session.commit()

    login_res = await client.post(
        "/api/v1/auth/login",
        json={
            "email": settings.SUPERADMIN_EMAIL,
            "password": settings.SUPERADMIN_PASSWORD,
        },
    )
    assert login_res.status_code == 200, f"Superadmin login failed: {login_res.json()}"
    csrf = login_res.cookies.get("csrf_token")
    if csrf:
        client.headers["x-csrf-token"] = csrf
    return client


class TestThemeEndpoints:

    async def test_get_active_theme_public(self, client: AsyncClient):
        """Public endpoint returns active theme even on fresh database."""
        res = await client.get("/api/v1/theme/active")
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Chovique Classic"
        assert "button_color" in data
        assert "button_text_color" in data
        assert "font_family" in data
        assert "heading_font_family" in data
        assert "number_font_family" in data

    async def test_superadmin_theme_lifecycle(self, client: AsyncClient):
        """Superadmin can list, create, edit, activate, and reset themes."""
        sa_client = await _get_superadmin_client(client)

        # 1. List themes
        list_res = await sa_client.get("/api/v1/superadmin/themes")
        assert list_res.status_code == 200
        theme_list = list_res.json()
        assert len(theme_list["items"]) >= 1

        # 2. Create custom theme
        create_payload = {
            "name": "Midnight Gold Edition",
            "description": "Ultra luxury dark theme",
            "primary_brand_color": "#111111",
            "background_color": "#000000",
            "luxury_gold_color": "#FFD700",
            "secondary_accent_color": "#E5A93C",
            "text_color": "#FFFFFF",
            "surface_color": "#181818",
            "button_color": "#FFD700",
            "button_text_color": "#000000",
            "secondary_button_color": "#E5A93C",
            "cart_color": "#FFD700",
            "cart_text_color": "#000000",
            "product_card_color": "#1C1C1C",
            "product_card_border_color": "#FFD700",
            "product_card_text_color": "#FFFFFF",
            "navbar_color": "#050505",
            "navbar_text_color": "#FFD700",
            "footer_color": "#000000",
            "footer_text_color": "#CCCCCC",
            "font_family": "Inter",
            "heading_font_family": "Playfair Display",
            "number_font_family": "Outfit",
        }
        create_res = await sa_client.post("/api/v1/superadmin/themes", json=create_payload)
        assert create_res.status_code == 201
        created_theme = create_res.json()
        assert created_theme["name"] == "Midnight Gold Edition"
        theme_id = created_theme["id"]

        # 3. Update theme
        update_payload = {
            **create_payload,
            "button_color": "#E0B034",
        }
        update_res = await sa_client.put(f"/api/v1/superadmin/themes/{theme_id}", json=update_payload)
        assert update_res.status_code == 200
        assert update_res.json()["button_color"] == "#E0B034"

        # 4. Activate theme
        act_res = await sa_client.post(f"/api/v1/superadmin/themes/{theme_id}/apply")
        assert act_res.status_code == 200

        # Check public active theme matches
        public_active = await client.get("/api/v1/theme/active")
        assert public_active.status_code == 200
        assert public_active.json()["id"] == theme_id
        assert public_active.json()["button_color"] == "#E0B034"

        # 5. Reset theme
        reset_res = await sa_client.post("/api/v1/superadmin/themes/reset")
        assert reset_res.status_code == 200
        assert reset_res.json()["name"] == "Chovique Classic"


class TestAuditLogEndpoints:

    async def test_audit_log_single_and_bulk_delete(self, client: AsyncClient):
        """Superadmin can delete audit log entries singly and in bulk."""
        sa_client = await _get_superadmin_client(client)

        # Seed two audit log entries
        async with TestSessionLocal() as session:
            log1 = AuditLog(
                user_id=None,
                user_role="admin",
                action="UPDATE_ORDER",
                entity_type="order",
                entity_id="order-101",
                module="orders",
                details="Updated order status",
            )
            log2 = AuditLog(
                user_id=None,
                user_role="admin",
                action="DELETE_COUPON",
                entity_type="coupon",
                entity_id="coupon-202",
                module="coupons",
                details="Deleted coupon",
            )
            session.add_all([log1, log2])
            await session.commit()
            await session.refresh(log1)
            await session.refresh(log2)
            id1 = str(log1.id)
            id2 = str(log2.id)

        # 1. Single delete log1
        del1_res = await sa_client.delete(f"/api/v1/superadmin/audit-logs/{id1}")
        assert del1_res.status_code == 200
        assert del1_res.json()["success"] is True

        # Verify log1 is gone (404)
        get1_res = await sa_client.get(f"/api/v1/superadmin/audit-logs/{id1}")
        assert get1_res.status_code == 404

        # 2. Bulk delete log2
        bulk_res = await sa_client.post(
            "/api/v1/superadmin/audit-logs/bulk-delete",
            json={"log_ids": [id2]},
        )
        assert bulk_res.status_code == 200
        assert bulk_res.json()["deleted_count"] == 1

        # Verify log2 is gone
        get2_res = await sa_client.get(f"/api/v1/superadmin/audit-logs/{id2}")
        assert get2_res.status_code == 404
