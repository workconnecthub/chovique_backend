"""add otp_daily_limits table

Revision ID: 014
Revises: 013
Create Date: 2026-10-25 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'otp_daily_limits' not in existing_tables:
        op.create_table(
            'otp_daily_limits',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('identifier', sa.String(100), nullable=False, index=True),
            sa.Column('send_date', sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column('send_count', sa.Integer(), nullable=False, server_default='1'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_otp_daily_limits_identifier_send_date', 'otp_daily_limits', ['identifier', 'send_date'])
        op.create_unique_constraint('uq_otp_daily_limit_identifier_date', 'otp_daily_limits', ['identifier', 'send_date'])


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'otp_daily_limits' in existing_tables:
        op.drop_table('otp_daily_limits')
