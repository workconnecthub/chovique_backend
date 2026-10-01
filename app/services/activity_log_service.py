from datetime import datetime, timezone, date
from typing import Optional, Tuple, List
from sqlalchemy import select, func, or_, and_, cast, String, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User
from app.models.audit_log import AuditLog
from app.schemas.admin_activity_log import ActivityLogResponse, ActivityLogListResponse


async def log_admin_activity(
    db: AsyncSession,
    admin_id: Optional[str],
    action: str,
    module: str,
    description: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    status: str = "SUCCESS",
) -> None:
    """Log an immutable admin activity entry into the audit_log table."""
    try:
        log_entry = AuditLog(
            user_id=admin_id,
            user_role="admin",
            action=action.upper().strip(),
            module=module.lower().strip(),
            endpoint=module.lower().strip(),
            status=status.upper().strip(),
            ip_address=ip_address or "127.0.0.1",
            user_agent=user_agent or "System",
            details=description,
        )
        db.add(log_entry)
        await db.commit()
    except Exception as e:
        await db.rollback()
        import logging
        logging.getLogger(__name__).error("Failed to write activity log: %s", e)


class ActivityLogService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_activity_logs(
        self,
        page: int = 1,
        limit: int = 20,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        module: Optional[str] = None,
        action: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> ActivityLogListResponse:
        query = select(AuditLog).outerjoin(User, AuditLog.user_id == User.id).options(selectinload(AuditLog.user))

        # Strict DB-level exclusion of Super Admin / Enterprise Chief administrative records
        # Admin Activity Logs must only show Admin and Customer activities
        SUPERADMIN_ROLES = ["superadmin", "super_admin", "enterprise_chief", "enterprise chief", "enterprise-chief"]
        SUPERADMIN_NAMES = ["enterprise chief", "superadmin", "super admin"]

        conditions = [
            and_(
                or_(
                    AuditLog.user_role == None,
                    ~func.lower(cast(AuditLog.user_role, String)).in_(SUPERADMIN_ROLES),
                ),
                or_(
                    AuditLog.user_id == None,
                    User.id == None,
                    and_(
                        ~func.lower(cast(User.role, String)).in_(SUPERADMIN_ROLES),
                        ~func.lower(cast(User.full_name, String)).in_(SUPERADMIN_NAMES),
                    ),
                ),
            )
        ]

        # Module filter
        if module and module.strip() and module.lower() != "all":
            conditions.append(func.lower(cast(AuditLog.module, String)) == module.lower().strip())

        # Action filter
        if action and action.strip() and action.lower() != "all":
            act_val = action.strip().lower()
            aliases = [act_val]
            if act_val in ["updated_profile", "update_admin_profile"]:
                aliases.extend(["updated_profile", "update_admin_profile"])
            elif act_val in ["changed_password", "change_admin_password"]:
                aliases.extend(["changed_password", "change_admin_password"])
            elif act_val in ["logged_in", "login"]:
                aliases.extend(["logged_in", "login"])
            elif act_val in ["logged_out", "logout"]:
                aliases.extend(["logged_out", "logout"])

            conditions.append(
                or_(
                    func.lower(cast(AuditLog.action, String)).in_(aliases),
                    cast(AuditLog.action, String).ilike(f"%{act_val}%"),
                )
            )

        # Status filter
        if status and status.strip() and status.lower() != "all":
            conditions.append(func.lower(cast(AuditLog.status, String)) == status.lower().strip())

        # Start Date filter (Inclusive from 00:00:00 of start_date)
        if start_date and start_date.strip():
            try:
                raw_start = start_date.strip()
                if "T" in raw_start:
                    d_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).date()
                else:
                    d_start = datetime.strptime(raw_start[:10], "%Y-%m-%d").date()
                conditions.append(cast(AuditLog.created_at, Date) >= d_start)
            except Exception:
                pass

        # End Date filter (Inclusive through 23:59:59 of end_date)
        if end_date and end_date.strip():
            try:
                raw_end = end_date.strip()
                if "T" in raw_end:
                    d_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00")).date()
                else:
                    d_end = datetime.strptime(raw_end[:10], "%Y-%m-%d").date()
                conditions.append(cast(AuditLog.created_at, Date) <= d_end)
            except Exception:
                pass

        # Search filter (details, action, module, admin name, admin email)
        if search and search.strip():
            s_pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    AuditLog.action.ilike(s_pattern),
                    AuditLog.module.ilike(s_pattern),
                    AuditLog.endpoint.ilike(s_pattern),
                    User.full_name.ilike(s_pattern),
                    User.email.ilike(s_pattern),
                )
            )

        if conditions:
            query = query.where(and_(*conditions))

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total_res = await self.db.execute(count_query)
        total = total_res.scalar_one_or_none() or 0

        # Pagination & Ordering
        offset = (page - 1) * limit
        query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)

        result = await self.db.execute(query)
        logs = result.scalars().all()

        items: List[ActivityLogResponse] = []
        for log in logs:
            desc = log.details or f"{log.action} in {log.module}"
            r_val = log.user_role or (log.user.role if log.user else "admin")
            items.append(
                ActivityLogResponse(
                    id=log.id,
                    admin_id=log.user_id,
                    admin_name=log.user.full_name if log.user else "System Admin",
                    admin_email=log.user.email if log.user else None,
                    user_role=r_val,
                    action=log.action,
                    module=log.module,
                    description=desc,
                    ip_address=log.ip_address,
                    user_agent=log.user_agent,
                    status=log.status,
                    created_at=log.created_at,
                )
            )

        return ActivityLogListResponse(
            items=items,
            total=total,
            page=page,
            limit=limit,
        )

    async def delete_activity_logs(self, log_ids: List[str]) -> int:
        """Delete multiple activity logs by their IDs."""
        if not log_ids:
            return 0
        from sqlalchemy import delete
        stmt = delete(AuditLog).where(AuditLog.id.in_(log_ids))
        res = await self.db.execute(stmt)
        await self.db.commit()
        return res.rowcount or 0

