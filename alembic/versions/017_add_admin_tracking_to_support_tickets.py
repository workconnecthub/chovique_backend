"""add admin tracking and updated_at to support_tickets

Revision ID: 017
Revises: 016
Create Date: 2026-10-26 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'support_tickets' in existing_tables:
        columns = [c['name'] for c in inspector.get_columns('support_tickets')]
        if 'assigned_admin' not in columns:
            op.add_column(
                'support_tickets',
                sa.Column('assigned_admin', sa.String(120), nullable=True)
            )
        if 'updated_at' not in columns:
            op.add_column(
                'support_tickets',
                sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True)
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'support_tickets' in existing_tables:
        columns = [c['name'] for c in inspector.get_columns('support_tickets')]
        if 'updated_at' in columns:
            op.drop_column('support_tickets', 'updated_at')
        if 'assigned_admin' in columns:
            op.drop_column('support_tickets', 'assigned_admin')
