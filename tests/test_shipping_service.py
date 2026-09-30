"""
Tests for Address V2 and Dual-Mode Fulfillment Logistics (Local Delivery vs Courier).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.models.address import CustomerAddress
from app.models.delivery_service_area import DeliveryServiceArea
from app.models.order import Order
from app.models.product import Product
from app.models.store_location import StoreLocation
from app.models.user import User
from app.services.superadmin_service import ensure_superadmin_exists
from tests.conftest import TestSessionLocal

pytestmark = pytest.mark.asyncio


async def _seed_logistics_and_product():
    """Seed flagship store, local service area, and test product."""
    async with TestSessionLocal() as session:
        # Seed store
        store_res = await session.execute(select(StoreLocation).where(StoreLocation.pincode == "530017"))
        store = store_res.scalars().first()
        if not store:
            store = StoreLocation(
                name="Chovique Flagship Store",
                house_number="Plot 42",
                street="Sector 1, MVP Colony",
                area="MVP Colony",
                city="Visakhapatnam",
                district="Visakhapatnam",
                state="Andhra Pradesh",
                pincode="530017",
                latitude=17.7412,
                longitude=83.3364,
                formatted_address="Plot 42, Sector 1, MVP Colony, Visakhapatnam, Andhra Pradesh 530017",
                phone="+91 891 2345678",
                is_primary=True,
                active=True,
            )
            session.add(store)
            await session.flush()

        # Seed local delivery service area (530017 - MVP Colony)
        area_res = await session.execute(select(DeliveryServiceArea).where(DeliveryServiceArea.pincode == "530017"))
        area = area_res.scalars().first()
        if not area:
            area = DeliveryServiceArea(
                store_location_id=store.id,
                pincode="530017",
                city="Visakhapatnam",
                district="Visakhapatnam",
                state="Andhra Pradesh",
                delivery_mode="LOCAL",
                delivery_charge=40.0,
                free_delivery_threshold=1000.0,
                same_day_available=True,
                estimated_delivery="Within 2-3 hours (Same Day)",
                active=True,
            )
            session.add(area)

        # Seed test product
        prod_res = await session.execute(select(Product).where(Product.id == "p_logistics"))
        if not prod_res.scalars().first():
            prod = Product(
                id="p_logistics",
                name="Artisanal Dark Bar",
                slug="artisanal-dark-bar",
                description="Pure 72% dark single origin chocolate",
                price=500.0,
                stock=100,
                is_active=True,
                is_featured=True,
            )
            session.add(prod)

        await session.commit()
        return store.id


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
    assert login_res.status_code == 200
    csrf = login_res.cookies.get("csrf_token")
    if csrf:
        client.headers["x-csrf-token"] = csrf
    return client


class TestShippingCalculation:

    async def test_calculate_local_delivery(self, client: AsyncClient):
        await _seed_logistics_and_product()

        # Local pincode 530017 with subtotal below threshold (500 < 1000)
        res = await client.post(
            "/api/v1/shipping/calculate",
            json={
                "pincode": "530017",
                "subtotal": 500.0,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_serviceable"] is True
        assert data["fulfillment_type"] == "LOCAL"
        assert data["delivery_charge"] == 40.0
        assert data["is_free_delivery"] is False
        assert data["estimated_delivery"] == "Within 2-3 hours (Same Day)"
        assert data["origin_store"] == "Chovique Flagship Store"

    async def test_calculate_local_free_delivery_threshold(self, client: AsyncClient):
        await _seed_logistics_and_product()

        # Local pincode 530017 with subtotal above threshold (1200 >= 1000)
        res = await client.post(
            "/api/v1/shipping/calculate",
            json={
                "pincode": "530017",
                "subtotal": 1200.0,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_serviceable"] is True
        assert data["fulfillment_type"] == "LOCAL"
        assert data["delivery_charge"] == 0.0
        assert data["is_free_delivery"] is True

    async def test_calculate_courier_delivery(self, client: AsyncClient):
        await _seed_logistics_and_product()

        # Destination outside local service area (520010 - Vijayawada)
        res = await client.post(
            "/api/v1/shipping/calculate",
            json={
                "pincode": "520010",
                "subtotal": 300.0,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["is_serviceable"] is True
        assert data["fulfillment_type"] == "COURIER"
        assert data["delivery_charge"] > 0
        assert "Courier" in data["fulfillment_type"] or data["fulfillment_type"] == "COURIER"

    async def test_calculate_invalid_pincode(self, client: AsyncClient):
        res = await client.post(
            "/api/v1/shipping/calculate",
            json={
                "pincode": "123",  # invalid pincode length
                "subtotal": 500.0,
            },
        )
        assert res.status_code in (400, 422)


class TestCustomerAddressV2:

    async def test_create_address_with_verified_coordinates(self, authenticated_client: AsyncClient):
        payload = {
            "title": "Apartment",
            "name": "Priya Sharma",
            "house_number": "Flat 402, Sea Pearl",
            "street": "Beach Road, Sector 3",
            "area": "MVP Colony",
            "landmark": "Opposite Shivaji Park",
            "city": "Visakhapatnam",
            "district": "Visakhapatnam",
            "state": "Andhra Pradesh",
            "zip": "530017",
            "phone": "9876543210",
            "latitude": 17.7412,
            "longitude": 83.3364,
            "formatted_address": "Flat 402, Sea Pearl, Beach Road, Sector 3, MVP Colony, Visakhapatnam, 530017",
            "google_place_id": "ChIJAw_PLACE_123",
            "location_source": "GOOGLE_PLACE",
            "location_verified": True,
            "isDefault": True,
        }
        res = await authenticated_client.post("/api/v1/users/me/addresses", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["house_number"] == "Flat 402, Sea Pearl"
        assert data["area"] == "MVP Colony"
        assert data["landmark"] == "Opposite Shivaji Park"
        assert data["latitude"] == 17.7412
        assert data["longitude"] == 83.3364
        assert data["location_source"] == "GOOGLE_PLACE"
        assert data["location_verified"] is True

    async def test_zero_fabricated_coordinates(self, authenticated_client: AsyncClient):
        """When address is entered manually without map/GPS, coordinates MUST remain null."""
        payload = {
            "title": "Office",
            "name": "Priya Sharma",
            "house_number": "Suite 101",
            "street": "Main Road",
            "city": "Visakhapatnam",
            "state": "Andhra Pradesh",
            "zip": "530017",
            "phone": "9876543210",
            "latitude": None,
            "longitude": None,
            "location_source": "MANUAL",
            "location_verified": False,
            "isDefault": False,
        }
        res = await authenticated_client.post("/api/v1/users/me/addresses", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["latitude"] is None
        assert data["longitude"] is None
        assert data["location_source"] == "MANUAL"
        assert data["location_verified"] is False


class TestOrderSnapshotAndLogisticsRouting:

    async def test_order_placement_records_authoritative_snapshot(self, authenticated_client: AsyncClient):
        await _seed_logistics_and_product()

        # 1. Create a customer address with full V2 fields
        addr_res = await authenticated_client.post(
            "/api/v1/users/me/addresses",
            json={
                "title": "Home",
                "name": "Ravi Teja",
                "house_number": "D.No 1-2-3",
                "street": "MVP Double Road",
                "area": "MVP Colony",
                "landmark": "Near Rythu Bazaar",
                "city": "Visakhapatnam",
                "district": "Visakhapatnam",
                "state": "Andhra Pradesh",
                "zip": "530017",
                "phone": "9848022338",
                "latitude": 17.7450,
                "longitude": 83.3390,
                "formatted_address": "D.No 1-2-3, MVP Double Road, MVP Colony, Visakhapatnam 530017",
                "google_place_id": "PLACE_MVP_456",
                "location_source": "GOOGLE_PLACE",
                "location_verified": True,
                "isDefault": True,
            },
        )
        assert addr_res.status_code == 201
        addr_data = addr_res.json()
        addr_id = addr_data["id"]

        # 2. Add product to cart
        cart_res = await authenticated_client.post(
            "/api/v1/cart",
            json={"product_id": "p_logistics", "quantity": 1},
        )
        assert cart_res.status_code in (200, 201)

        # 3. Place order using shipping address snapshot
        order_res = await authenticated_client.post(
            "/api/v1/orders",
            json={
                "items": [{"product_id": "p_logistics", "quantity": 1}],
                "shipping_address": {
                    "name": "Ravi Teja",
                    "house_number": "D.No 1-2-3",
                    "street": "MVP Double Road",
                    "area": "MVP Colony",
                    "landmark": "Near Rythu Bazaar",
                    "city": "Visakhapatnam",
                    "district": "Visakhapatnam",
                    "state": "Andhra Pradesh",
                    "zip": "530017",
                    "phone": "9848022338",
                    "latitude": 17.7450,
                    "longitude": 83.3390,
                    "formatted_address": "D.No 1-2-3, MVP Double Road, MVP Colony, Visakhapatnam 530017",
                    "google_place_id": "PLACE_MVP_456",
                    "location_source": "GOOGLE_PLACE",
                    "location_verified": True,
                },
                "payment_method": "UPI",
                "delivery_option": "Standard Delivery",
            },
        )
        assert order_res.status_code == 201
        order_data = order_res.json()
        order_id = order_data["id"]

        # Verify response snapshot
        assert order_data["fulfillment_type"] == "LOCAL"
        assert order_data["shipping"] == 40.0
        assert order_data["shipping_address"]["house_number"] == "D.No 1-2-3"
        assert order_data["shipping_address"]["latitude"] == 17.7450
        assert order_data["shipping_address"]["longitude"] == 83.3390
        assert order_data["shipping_address"]["location_source"] == "GOOGLE_PLACE"
        assert order_data["shipping_address"]["location_verified"] is True

        # 4. Verify authoritative columns in DB
        async with TestSessionLocal() as session:
            db_order = await session.get(Order, order_id)
            assert db_order is not None
            assert db_order.fulfillment_type == "LOCAL"
            assert db_order.shipping_name == "Ravi Teja"
            assert db_order.shipping_house_number == "D.No 1-2-3"
            assert db_order.shipping_street == "MVP Double Road"
            assert db_order.shipping_pincode == "530017"
            assert db_order.shipping_latitude == 17.7450
            assert db_order.shipping_longitude == 83.3390
            assert db_order.shipping_delivery_charge == 40.0
            assert db_order.shipping_location_verified is True
            # Check JSON compatibility
            assert db_order.shipping_address.get("pincode") == "530017"


class TestSuperadminLogisticsAPI:

    async def test_manage_store_locations(self, client: AsyncClient):
        sa_client = await _get_superadmin_client(client)

        # List store locations
        res = await sa_client.get("/api/v1/superadmin/logistics/stores")
        assert res.status_code == 200
        stores = res.json()
        assert isinstance(stores, list)

        # Create new secondary store location
        create_res = await sa_client.post(
            "/api/v1/superadmin/logistics/stores",
            json={
                "name": "Chovique Gajuwaka Hub",
                "house_number": "D.No 12-4",
                "street": "Main Road, Gajuwaka",
                "city": "Visakhapatnam",
                "state": "Andhra Pradesh",
                "pincode": "530026",
                "latitude": 17.6890,
                "longitude": 83.2180,
                "phone": "9848011223",
                "is_primary": False,
                "active": True,
            },
        )
        assert create_res.status_code == 201
        new_store = create_res.json()
        assert new_store["name"] == "Chovique Gajuwaka Hub"
        assert new_store["pincode"] == "530026"

    async def test_manage_service_areas(self, client: AsyncClient):
        sa_client = await _get_superadmin_client(client)

        # List service areas
        res = await sa_client.get("/api/v1/superadmin/logistics/service-areas")
        assert res.status_code == 200
        areas = res.json()
        assert isinstance(areas, list)

        # Create service area for Madhurawada (530048)
        create_res = await sa_client.post(
            "/api/v1/superadmin/logistics/service-areas",
            json={
                "pincode": "530048",
                "city": "Visakhapatnam",
                "district": "Visakhapatnam",
                "state": "Andhra Pradesh",
                "delivery_mode": "LOCAL",
                "delivery_charge": 50.0,
                "free_delivery_threshold": 1200.0,
                "same_day_available": True,
                "estimated_delivery": "Within 4-5 hours (Same Day)",
                "active": True,
            },
        )
        assert create_res.status_code == 201
        new_area = create_res.json()
        assert new_area["pincode"] == "530048"
        assert new_area["delivery_charge"] == 50.0
