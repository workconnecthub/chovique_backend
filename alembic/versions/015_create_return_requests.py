"""create return_requests table and support_tickets return columns

Revision ID: 015
Revises: 014
Create Date: 2026-10-26 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'return_requests' not in existing_tables:
        op.create_table(
            'return_requests',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('order_id', sa.String(36), sa.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, unique=True),
            sa.Column('ticket_id', sa.String(36), sa.ForeignKey('support_tickets.id', ondelete='SET NULL'), nullable=True),
            sa.Column('customer_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('customer_name', sa.String(120), nullable=False),
            sa.Column('customer_email', sa.String(255), nullable=True),
            sa.Column('customer_phone', sa.String(50), nullable=True),
            sa.Column('order_amount', sa.Float(), nullable=False),
            sa.Column('payment_method', sa.String(100), nullable=False),
            sa.Column('delivery_address', sa.JSON(), nullable=False),
            sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('reason', sa.String(100), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('photo_url', sa.String(500), nullable=True),
            sa.Column('status', sa.String(50), nullable=False, server_default='Pending'),
            sa.Column('admin_notes', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index('ix_return_requests_order_id', 'return_requests', ['order_id'])
        op.create_index('ix_return_requests_customer_id', 'return_requests', ['customer_id'])
        op.create_index('ix_return_requests_status', 'return_requests', ['status'])

    # Add photo_url and return_request_id to support_tickets if not present
    if 'support_tickets' in existing_tables:
        ticket_cols = [c['name'] for c in inspector.get_columns('support_tickets')]
        if 'photo_url' not in ticket_cols:
            op.add_column('support_tickets', sa.Column('photo_url', sa.String(500), nullable=True))
        if 'return_request_id' not in ticket_cols:
            op.add_column('support_tickets', sa.Column('return_request_id', sa.String(36), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'support_tickets' in existing_tables:
        ticket_cols = [c['name'] for c in inspector.get_columns('support_tickets')]
        if 'return_request_id' in ticket_cols:
            op.drop_column('support_tickets', 'return_request_id')
        if 'photo_url' in ticket_cols:
            op.drop_column('support_tickets', 'photo_url')

    if 'return_requests' in existing_tables:
        op.drop_table('return_requests')
