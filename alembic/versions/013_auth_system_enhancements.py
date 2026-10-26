"""auth system enhancements

Revision ID: 013
Revises: 012
Create Date: 2026-10-25 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create otp_challenges table if not exists
    if 'otp_challenges' not in existing_tables:
        op.create_table(
            'otp_challenges',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('identifier', sa.String(100), nullable=False, index=True),
            sa.Column('purpose', sa.String(50), nullable=False, server_default='customer_login'),
            sa.Column('hashed_otp', sa.String(255), nullable=False),
            sa.Column('salt', sa.String(64), nullable=False),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
            sa.Column('resend_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_sent_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('is_consumed', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index('ix_otp_challenges_identifier_purpose', 'otp_challenges', ['identifier', 'purpose'])

    user_columns = [col['name'] for col in inspector.get_columns('users')]
    if 'is_phone_verified' not in user_columns:
        op.add_column('users', sa.Column('is_phone_verified', sa.Boolean(), nullable=False, server_default=sa.false()))

    # Make users.email and users.full_name nullable for phone-based customer creation
    if conn.dialect.name == 'postgresql':
        op.execute("ALTER TABLE users ALTER COLUMN email DROP NOT NULL;")
        op.execute("ALTER TABLE users ALTER COLUMN full_name DROP NOT NULL;")
        op.execute("CREATE INDEX IF NOT EXISTS ix_users_phone ON users (phone);")
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_customer_phone ON users (phone) WHERE phone IS NOT NULL AND role = 'customer';")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if 'otp_challenges' in existing_tables:
        op.drop_table('otp_challenges')

    user_columns = [col['name'] for col in inspector.get_columns('users')]
    if 'is_phone_verified' in user_columns:
        op.drop_column('users', 'is_phone_verified')

    if conn.dialect.name == 'postgresql':
        op.execute("DROP INDEX IF EXISTS uq_users_customer_phone;")
        op.execute("DROP INDEX IF EXISTS ix_users_phone;")
