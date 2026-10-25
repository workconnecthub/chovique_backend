"""add is_sample and sample_price to products

Revision ID: 012
Revises: 011
Create Date: 2026-10-25 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('products')]

    if 'is_sample' not in existing_columns:
        op.add_column('products', sa.Column('is_sample', sa.Boolean(), nullable=False, server_default=sa.false()))
    if 'sample_price' not in existing_columns:
        op.add_column('products', sa.Column('sample_price', sa.Float(), nullable=True))
    if 'is_available' not in existing_columns:
        op.add_column('products', sa.Column('is_available', sa.Boolean(), nullable=False, server_default=sa.true()))
    if 'sort_order' not in existing_columns:
        op.add_column('products', sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'))
    if 'hover_image' not in existing_columns:
        op.add_column('products', sa.Column('hover_image', sa.Text(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_columns = [col['name'] for col in inspector.get_columns('products')]

    if 'hover_image' in existing_columns:
        op.drop_column('products', 'hover_image')
    if 'sort_order' in existing_columns:
        op.drop_column('products', 'sort_order')
    if 'is_available' in existing_columns:
        op.drop_column('products', 'is_available')
    if 'sample_price' in existing_columns:
        op.drop_column('products', 'sample_price')
    if 'is_sample' in existing_columns:
        op.drop_column('products', 'is_sample')
