"""
Migration: Create superadmin_notifications table and indexes.
Run with: python scripts/migrate_superadmin_notifications.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import create_engine, text

RAW_URL = os.environ.get("DATABASE_URL", "")
SYNC_URL = RAW_URL.replace("postgresql+asyncpg", "postgresql")

engine = create_engine(SYNC_URL, echo=False)

DDL = """
CREATE TABLE IF NOT EXISTS superadmin_notifications (
    id                      VARCHAR(36) PRIMARY KEY,
    title                   VARCHAR(300) NOT NULL,
    message                 TEXT NOT NULL,
    category                VARCHAR(50) NOT NULL,
    severity                VARCHAR(20) NOT NULL DEFAULT 'INFO',
    is_read                 BOOLEAN NOT NULL DEFAULT FALSE,
    read_at                 TIMESTAMPTZ,
    related_entity_type     VARCHAR(100),
    related_entity_id       VARCHAR(100),
    related_user_id         VARCHAR(36) REFERENCES users(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_superadmin_notifications_category ON superadmin_notifications (category);
CREATE INDEX IF NOT EXISTS ix_superadmin_notifications_severity ON superadmin_notifications (severity);
CREATE INDEX IF NOT EXISTS ix_superadmin_notifications_is_read ON superadmin_notifications (is_read);
CREATE INDEX IF NOT EXISTS ix_superadmin_notifications_created_at ON superadmin_notifications (created_at);
CREATE INDEX IF NOT EXISTS ix_sa_notif_category_is_read ON superadmin_notifications (category, is_read);
CREATE INDEX IF NOT EXISTS ix_sa_notif_severity_created ON superadmin_notifications (severity, created_at);
"""

def main():
    with engine.connect() as conn:
        print("Creating superadmin_notifications table and indexes...")
        conn.execute(text(DDL))
        conn.commit()
        print("Done! superadmin_notifications table created.")

if __name__ == "__main__":
    main()
