"""
Safe, Dependency-Aware Demo/Seed Data Cleanup Utility
====================================================
Inspects and safely cleans up demo/seed data while preserving:
- The configured Super Admin account (superadmin@chovique.com / +919876543210)
- Real customer accounts, orders, products, and user-created data

Usage:
    python scripts/cleanup_demo_data.py             # Dry run (safe preview only, default)
    python scripts/cleanup_demo_data.py --dry-run   # Explicit dry run
    python scripts/cleanup_demo_data.py --apply     # Execute deletion with confirmation
    python scripts/cleanup_demo_data.py --apply --force # Execute without interactive prompt
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.core.config import settings
from app.db.session import engine
from app.integrations.msg91 import parse_and_normalize_phone


async def inspect_and_cleanup(dry_run: bool = True, include_test_accounts: bool = False):
    superadmin_email = (settings.SUPERADMIN_EMAIL or "superadmin@chovique.com").strip().lower()
    superadmin_phone = (settings.SUPERADMIN_PHONE or "919876543210").strip()
    try:
        norm_sa_phone, _, _ = parse_and_normalize_phone(superadmin_phone, default_country_code="+91")
    except Exception:
        norm_sa_phone = superadmin_phone

    print("=" * 70)
    print("CHOVIQUE DATABASE DEMO/SEED DATA INSPECTION & CLEANUP")
    print("=" * 70)
    print(f"Mode: {'[DRY RUN - PREVIEW ONLY]' if dry_run else '[APPLY - EXECUTE CHANGES]'}")
    print(f"Protected Super Admin Email: {superadmin_email}")
    print(f"Protected Super Admin Phone: {norm_sa_phone}")
    print("-" * 70)

    async with engine.connect() as conn:
        # 1. Inspect all users
        user_rows = (await conn.execute(text(
            "SELECT id, full_name, email, phone, role, is_active, created_at FROM users"
        ))).fetchall()

        superadmin_records = []
        legacy_demo_accounts = []
        user_test_accounts = []

        for row in user_rows:
            uid, name, email, phone, role, active, created = row
            clean_email = (email or "").strip().lower()
            clean_phone = (phone or "").strip()

            # Identify genuine configured Super Admin
            if (clean_email == superadmin_email or 
                clean_phone == norm_sa_phone or 
                clean_phone == norm_sa_phone.lstrip("+")):
                superadmin_records.append(row)
            # Identify legacy demo placeholder
            elif clean_email == "admin@chovique.com":
                legacy_demo_accounts.append(row)
            else:
                user_test_accounts.append(row)

        print("\n[1] USER ACCOUNTS ANALYSIS:")
        print(f"  * Configured Super Admin (PROTECTED, WILL NOT BE DELETED): {len(superadmin_records)}")
        for u in superadmin_records:
            print(f"    - ID: {u[0]} | Name: {u[1]} | Email: {u[2]} | Phone: {u[3]} | Role: {u[4]}")

        print(f"\n  * Legacy Demo Seed Accounts (FLAGGED FOR REMOVAL): {len(legacy_demo_accounts)}")
        for u in legacy_demo_accounts:
            print(f"    - ID: {u[0]} | Name: {u[1]} | Email: {u[2]} | Phone: {u[3]} | Role: {u[4]}")

        print(f"\n  * Other Accounts (PRESERVED unless --include-test-accounts): {len(user_test_accounts)}")
        for u in user_test_accounts:
            print(f"    - ID: {u[0]} | Name: {u[1]} | Email: {u[2]} | Phone: {u[3]} | Role: {u[4]}")

        target_user_ids = [u[0] for u in legacy_demo_accounts]
        if include_test_accounts:
            target_user_ids.extend([u[0] for u in user_test_accounts])

        # 2. Inspect demo notifications
        demo_notifs = (await conn.execute(text(
            "SELECT id, title, category FROM superadmin_notifications WHERE id LIKE 'demo-sa-notif-%'"
        ))).fetchall()
        print(f"\n[2] DEMO SUPERADMIN NOTIFICATIONS (FLAGGED FOR REMOVAL): {len(demo_notifs)}")
        for n in demo_notifs:
            print(f"    - ID: {n[0]} | Title: {n[1]} | Category: {n[2]}")

        # 3. Inspect demo store locations & delivery areas
        demo_stores = (await conn.execute(text(
            "SELECT id, name, city FROM store_locations WHERE name ILIKE '%Flagship%'"
        ))).fetchall()
        print(f"\n[3] DEMO STORE LOCATIONS: {len(demo_stores)}")
        for s in demo_stores:
            print(f"    - ID: {s[0]} | Name: {s[1]} | City: {s[2]}")

        demo_areas = (await conn.execute(text(
            "SELECT id, pincode, city FROM delivery_service_areas WHERE city ILIKE '%Visakhapatnam%' AND pincode IN ('530001', '530002', '530003', '530004', '530007')"
        ))).fetchall()
        print(f"\n[4] DEMO DELIVERY SERVICE AREAS: {len(demo_areas)}")
        for a in demo_areas:
            print(f"    - ID: {a[0]} | Pincode: {a[1]} | City: {a[2]}")

        # 4. Check dependent records for target users
        dependent_summary = {}
        if target_user_ids:
            uid_tuple = tuple(target_user_ids)
            in_clause = "IN (" + ",".join(f"'{uid}'" for uid in target_user_ids) + ")"
            
            # Carts
            c_cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM carts WHERE user_id {in_clause}"))).scalar()
            dependent_summary["carts"] = c_cnt

            # Wallets & coin_transactions
            wallets_cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM user_wallets WHERE user_id {in_clause}"))).scalar()
            dependent_summary["user_wallets"] = wallets_cnt
            ct_cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM coin_transactions WHERE user_id {in_clause}"))).scalar()
            dependent_summary["coin_transactions"] = ct_cnt

            # Refresh tokens
            rt_cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM refresh_tokens WHERE user_id {in_clause}"))).scalar()
            dependent_summary["refresh_tokens"] = rt_cnt

            # Audit logs (we nullify user_id to preserve audit history)
            al_cnt = (await conn.execute(text(f"SELECT COUNT(*) FROM audit_logs WHERE user_id {in_clause}"))).scalar()
            dependent_summary["audit_logs (will set user_id=NULL)"] = al_cnt

        print("\n[5] DEPENDENT RECORDS TO CLEAN / NULLIFY:")
        for tbl, cnt in dependent_summary.items():
            print(f"    - {tbl}: {cnt}")

        # Summary of planned actions
        total_items = (
            len(target_user_ids)
            + len(demo_notifs)
            + len(demo_stores)
            + len(demo_areas)
        )

        print("\n" + "=" * 70)
        print(f"TOTAL DEMO/TARGET ENTITIES IDENTIFIED: {total_items}")
        print("=" * 70)

        if total_items == 0:
            print("Database is already clean! No demo/seed records found.")
            return

        if dry_run:
            print("\n[DRY RUN COMPLETE] No records were modified or deleted.")
            print("To execute this cleanup safely, run:")
            print("    python scripts/cleanup_demo_data.py --apply")
            return

        # Execution in a transaction
        print("\n[APPLYING CLEANUP...]")
        async with engine.begin() as tx:
            # 1. Nullify audit_logs for target users
            if target_user_ids:
                in_clause = "IN (" + ",".join(f"'{uid}'" for uid in target_user_ids) + ")"
                await tx.execute(text(f"UPDATE audit_logs SET user_id = NULL WHERE user_id {in_clause}"))
                print("  - Nullified user_id in audit_logs")

                # Delete refresh tokens
                await tx.execute(text(f"DELETE FROM refresh_tokens WHERE user_id {in_clause}"))
                print("  - Removed refresh_tokens")

                # Delete cart items & carts
                carts = (await tx.execute(text(f"SELECT id FROM carts WHERE user_id {in_clause}"))).fetchall()
                if carts:
                    c_ids = "IN (" + ",".join(f"'{c[0]}'" for c in carts) + ")"
                    await tx.execute(text(f"DELETE FROM cart_items WHERE cart_id {c_ids}"))
                await tx.execute(text(f"DELETE FROM carts WHERE user_id {in_clause}"))
                print("  - Removed carts")

                # Delete coin transactions & user wallets
                await tx.execute(text(f"DELETE FROM coin_transactions WHERE user_id {in_clause}"))
                await tx.execute(text(f"DELETE FROM user_wallets WHERE user_id {in_clause}"))
                print("  - Removed user_wallets and coin_transactions")

                # Nullify superadmin_notifications related_user_id
                await tx.execute(text(f"UPDATE superadmin_notifications SET related_user_id = NULL WHERE related_user_id {in_clause}"))

                # Delete target users
                await tx.execute(text(f"DELETE FROM users WHERE id {in_clause}"))
                print(f"  - Removed {len(target_user_ids)} demo/target user account(s)")

            # 2. Delete demo superadmin notifications
            if demo_notifs:
                await tx.execute(text("DELETE FROM superadmin_notifications WHERE id LIKE 'demo-sa-notif-%'"))
                print(f"  - Removed {len(demo_notifs)} demo notification(s)")

            # 3. Delete demo store locations & areas
            if demo_stores:
                await tx.execute(text("DELETE FROM store_locations WHERE name ILIKE '%Flagship%'"))
                print(f"  - Removed {len(demo_stores)} demo store location(s)")

            if demo_areas:
                await tx.execute(text("DELETE FROM delivery_service_areas WHERE city ILIKE '%Visakhapatnam%' AND pincode IN ('530001', '530002', '530003', '530004', '530007')"))
                print(f"  - Removed {len(demo_areas)} demo delivery service area(s)")

        print("\n[CLEANUP SUCCESSFUL] All target demo records have been safely removed.")
        print("Super Admin account preserved intact.")


def main():
    parser = argparse.ArgumentParser(description="Chovique Demo Data Cleanup Utility")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Preview records without making changes")
    parser.add_argument("--apply", action="store_true", default=False, help="Execute cleanup")
    parser.add_argument("--include-test-accounts", action="store_true", default=False, help="Also clean manual test accounts (e.g. vyshugampa)")
    parser.add_argument("--force", action="store_true", default=False, help="Skip confirmation prompt when using --apply")

    args = parser.parse_args()

    # Default to dry-run unless --apply is explicitly specified
    is_dry_run = True
    if args.apply:
        is_dry_run = False
        if not args.force:
            print("WARNING: This will permanently delete identified demo records from the database.")
            confirm = input("Are you sure you want to proceed? [y/N]: ").strip().lower()
            if confirm not in ("y", "yes"):
                print("Operation cancelled.")
                return

    asyncio.run(inspect_and_cleanup(
        dry_run=is_dry_run,
        include_test_accounts=args.include_test_accounts,
    ))


if __name__ == "__main__":
    main()
