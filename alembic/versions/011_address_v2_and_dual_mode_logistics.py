"""address v2 and dual mode logistics

Revision ID: 011
Revises: 010
Create Date: 2026-09-19 08:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # 1. Create store_locations table
    if 'store_locations' not in existing_tables:
        op.create_table(
            'store_locations',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('name', sa.String(120), nullable=False),
            sa.Column('house_number', sa.String(100), nullable=True),
            sa.Column('street', sa.String(255), nullable=False),
            sa.Column('area', sa.String(150), nullable=True),
            sa.Column('city', sa.String(100), nullable=False, server_default='Visakhapatnam'),
            sa.Column('district', sa.String(100), nullable=True),
            sa.Column('state', sa.String(100), nullable=False, server_default='Andhra Pradesh'),
            sa.Column('pincode', sa.String(10), nullable=False, index=True),
            sa.Column('latitude', sa.Float(), nullable=True),
            sa.Column('longitude', sa.Float(), nullable=True),
            sa.Column('formatted_address', sa.String(500), nullable=True),
            sa.Column('google_place_id', sa.String(255), nullable=True),
            sa.Column('phone', sa.String(30), nullable=True),
            sa.Column('is_primary', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 2. Create delivery_service_areas table
    if 'delivery_service_areas' not in existing_tables:
        op.create_table(
            'delivery_service_areas',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('store_location_id', sa.String(36), sa.ForeignKey('store_locations.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('pincode', sa.String(10), unique=True, nullable=False, index=True),
            sa.Column('city', sa.String(100), nullable=False, server_default='Visakhapatnam'),
            sa.Column('district', sa.String(100), nullable=True),
            sa.Column('state', sa.String(100), nullable=False, server_default='Andhra Pradesh'),
            sa.Column('delivery_mode', sa.String(50), nullable=False, server_default='LOCAL'),
            sa.Column('delivery_charge', sa.Float(), nullable=False, server_default='40.0'),
            sa.Column('free_delivery_threshold', sa.Float(), nullable=True),
            sa.Column('same_day_available', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('estimated_delivery', sa.String(100), nullable=False, server_default='Within 3-5 hours (Same Day)'),
            sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )

    # 3. Add columns to customer_addresses
    addr_cols = [c['name'] for c in inspector.get_columns('customer_addresses')]
    if 'house_number' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('house_number', sa.String(100), nullable=True))
    if 'area' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('area', sa.String(150), nullable=True))
    if 'landmark' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('landmark', sa.String(150), nullable=True))
    if 'district' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('district', sa.String(100), nullable=True))
    if 'latitude' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('latitude', sa.Float(), nullable=True))
    if 'longitude' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('longitude', sa.Float(), nullable=True))
    if 'formatted_address' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('formatted_address', sa.String(500), nullable=True))
    if 'google_place_id' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('google_place_id', sa.String(255), nullable=True))
    if 'location_source' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('location_source', sa.String(50), nullable=False, server_default='MANUAL'))
    if 'location_verified' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('location_verified', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'updated_at' not in addr_cols:
        op.add_column('customer_addresses', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

    # 4. Add columns to orders
    order_cols = [c['name'] for c in inspector.get_columns('orders')]
    if 'store_location_id' not in order_cols:
        op.add_column('orders', sa.Column('store_location_id', sa.String(36), sa.ForeignKey('store_locations.id', ondelete='SET NULL'), nullable=True))
    if 'fulfillment_type' not in order_cols:
        op.add_column('orders', sa.Column('fulfillment_type', sa.String(50), nullable=False, server_default='LOCAL'))
    if 'shipping_provider' not in order_cols:
        op.add_column('orders', sa.Column('shipping_provider', sa.String(50), nullable=False, server_default='INTERNAL'))
    if 'fulfillment_status' not in order_cols:
        op.add_column('orders', sa.Column('fulfillment_status', sa.String(50), nullable=False, server_default='UNASSIGNED'))
    if 'delivery_boy_id' not in order_cols:
        op.add_column('orders', sa.Column('delivery_boy_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))

    # Authoritative Snapshot columns
    if 'shipping_name' not in order_cols:
        op.add_column('orders', sa.Column('shipping_name', sa.String(120), nullable=True))
    if 'shipping_phone' not in order_cols:
        op.add_column('orders', sa.Column('shipping_phone', sa.String(30), nullable=True))
    if 'shipping_house_number' not in order_cols:
        op.add_column('orders', sa.Column('shipping_house_number', sa.String(100), nullable=True))
    if 'shipping_street' not in order_cols:
        op.add_column('orders', sa.Column('shipping_street', sa.String(255), nullable=True))
    if 'shipping_area' not in order_cols:
        op.add_column('orders', sa.Column('shipping_area', sa.String(150), nullable=True))
    if 'shipping_landmark' not in order_cols:
        op.add_column('orders', sa.Column('shipping_landmark', sa.String(150), nullable=True))
    if 'shipping_city' not in order_cols:
        op.add_column('orders', sa.Column('shipping_city', sa.String(100), nullable=True))
    if 'shipping_district' not in order_cols:
        op.add_column('orders', sa.Column('shipping_district', sa.String(100), nullable=True))
    if 'shipping_state' not in order_cols:
        op.add_column('orders', sa.Column('shipping_state', sa.String(100), nullable=True))
    if 'shipping_pincode' not in order_cols:
        op.add_column('orders', sa.Column('shipping_pincode', sa.String(20), nullable=True))
    if 'shipping_latitude' not in order_cols:
        op.add_column('orders', sa.Column('shipping_latitude', sa.Float(), nullable=True))
    if 'shipping_longitude' not in order_cols:
        op.add_column('orders', sa.Column('shipping_longitude', sa.Float(), nullable=True))
    if 'shipping_formatted_address' not in order_cols:
        op.add_column('orders', sa.Column('shipping_formatted_address', sa.String(500), nullable=True))
    if 'shipping_google_place_id' not in order_cols:
        op.add_column('orders', sa.Column('shipping_google_place_id', sa.String(255), nullable=True))
    if 'shipping_location_source' not in order_cols:
        op.add_column('orders', sa.Column('shipping_location_source', sa.String(50), nullable=True))
    if 'shipping_location_verified' not in order_cols:
        op.add_column('orders', sa.Column('shipping_location_verified', sa.Boolean(), nullable=True, server_default=sa.false()))
    if 'shipping_delivery_charge' not in order_cols:
        op.add_column('orders', sa.Column('shipping_delivery_charge', sa.Float(), nullable=True))
    if 'shipping_confirmed_at' not in order_cols:
        op.add_column('orders', sa.Column('shipping_confirmed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_table('delivery_service_areas')
    op.drop_table('store_locations')
