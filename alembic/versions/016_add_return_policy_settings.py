"""add return policy settings to platform_settings

Revision ID: 016
Revises: 015
Create Date: 2026-10-26 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('platform_settings')]

    if 'return_requests_enabled' not in columns:
        op.add_column(
            'platform_settings',
            sa.Column('return_requests_enabled', sa.Boolean(), nullable=False, server_default=sa.true())
        )

    if 'return_window_value' not in columns:
        op.add_column(
            'platform_settings',
            sa.Column('return_window_value', sa.Integer(), nullable=False, server_default='30')
        )

    if 'return_window_unit' not in columns:
        op.add_column(
            'platform_settings',
            sa.Column('return_window_unit', sa.String(20), nullable=False, server_default='minutes')
        )

    if 'return_photo_required' not in columns:
        op.add_column(
            'platform_settings',
            sa.Column('return_photo_required', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('platform_settings')]

    for col in ['return_photo_required', 'return_window_unit', 'return_window_value', 'return_requests_enabled']:
        if col in columns:
            op.drop_column('platform_settings', col)
