import io
import csv
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from fastapi import HTTPException, status

from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.superadmin_audit_logs import AuditLogResponse, AuditLogListResponse

IST = timezone(timedelta(hours=5, minutes=30))


async def record_audit_event(
    db: AsyncSession,
    action: str,
    module: str = "system",
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    ip_address: Optional[str] = "127.0.0.1",
    user_agent: Optional[str] = None,
    request_method: Optional[str] = "POST",
    endpoint: Optional[str] = None,
    status_str: str = "SUCCESS",
    metadata: Optional[Dict[str, Any]] = None,
):
    """Reusable service function to create an immutable audit record."""
    try:
        log_entry = AuditLog(
            user_id=user_id,
            user_role=user_role or "system",
            action=action.strip(),
            module=module.lower().strip(),
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
            request_method=request_method,
            endpoint=endpoint,
            status=status_str.upper().strip(),
            log_metadata=metadata or {},
        )
        db.add(log_entry)
        await db.flush()
    except Exception as e:
        print(f"Failed to record audit log: {e}")


class SuperadminAuditLogsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _to_response(self, log: AuditLog) -> AuditLogResponse:
        u_name = "System Process"
        u_email = None
        u_role = log.user_role or "system"

        if log.user:
            u_name = log.user.full_name
            u_email = log.user.email
            u_role = log.user.role

        formatted_dt = ""
        if log.created_at:
            dt = log.created_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            formatted_dt = dt.astimezone(IST).strftime("%d %b %Y, %I:%M %p")

        desc_val = log.details or (f"{log.action} in {log.module}" if log.module else log.action)

        return AuditLogResponse(
            id=log.id,
            user_id=log.user_id,
            user_name=u_name,
            user_email=u_email,
            user_role=u_role,
            action=log.action,
            module=log.module,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            description=desc_val,
            ip_address=log.ip_address or "127.0.0.1",
            user_agent=log.user_agent,
            request_method=log.request_method,
            endpoint=log.endpoint,
            status=log.status or "SUCCESS",
            metadata=log.log_metadata or {},
            created_at=formatted_dt,
        )

    async def list_audit_logs(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        module: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
    ) -> AuditLogListResponse:
        """Fetch paginated audit logs with search and multi-filtering."""
        stmt = select(AuditLog).options(selectinload(AuditLog.user))

        if user_id and user_id.strip() and user_id.strip().lower() not in ("all", "all users"):
            stmt = stmt.where(AuditLog.user_id == user_id.strip())

        if action and action.strip() and action.strip().lower() not in ("all", "all actions"):
            act_clean = action.strip().lower()
            act_alt = act_clean.replace(" ", "_")
            act_alt2 = act_clean.replace("_", " ")
            stmt = stmt.where(
                or_(
                    func.lower(AuditLog.action) == act_clean,
                    func.lower(AuditLog.action) == act_alt,
                    func.lower(AuditLog.action) == act_alt2,
                    AuditLog.action.ilike(f"%{act_clean}%"),
                )
            )

        if module and module.strip() and module.strip().lower() not in ("all", "all modules"):
            mod_clean = module.strip().lower()
            stmt = stmt.where(
                or_(
                    func.lower(AuditLog.module) == mod_clean,
                    AuditLog.module.ilike(f"%{mod_clean}%"),
                )
            )

        if status_filter and status_filter.strip() and status_filter.strip().lower() not in ("all", "all status"):
            stmt = stmt.where(func.lower(AuditLog.status) == status_filter.strip().lower())

        if date_from and date_from.strip():
            try:
                raw_from = date_from.strip()
                if len(raw_from) == 10:
                    dt_from = datetime.strptime(raw_from, "%Y-%m-%d")
                else:
                    dt_from = datetime.fromisoformat(raw_from)
                stmt = stmt.where(AuditLog.created_at >= dt_from)
            except Exception:
                pass

        if date_to and date_to.strip():
            try:
                raw_to = date_to.strip()
                if len(raw_to) == 10:
                    dt_to = datetime.strptime(raw_to, "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59, microsecond=999999
                    )
                else:
                    dt_to = datetime.fromisoformat(raw_to)
                    if dt_to.hour == 0 and dt_to.minute == 0 and dt_to.second == 0:
                        dt_to = dt_to.replace(hour=23, minute=59, second=59, microsecond=999999)
                stmt = stmt.where(AuditLog.created_at <= dt_to)
            except Exception:
                pass

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            stmt = stmt.outerjoin(User, AuditLog.user_id == User.id).where(
                or_(
                    AuditLog.action.ilike(pattern),
                    AuditLog.module.ilike(pattern),
                    AuditLog.endpoint.ilike(pattern),
                    AuditLog.entity_id.ilike(pattern),
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                )
            )

        # Count total records
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.db.execute(count_stmt)
        total_count = total_res.scalar_one() or 0

        # Paginated results
        stmt = stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
        logs_res = await self.db.execute(stmt)
        logs = logs_res.scalars().all()

        items = [self._to_response(l) for l in logs]

        return AuditLogListResponse(
            items=items,
            total=total_count,
            page=page,
            limit=limit,
        )

    async def get_audit_log_by_id(self, log_id: str) -> AuditLogResponse:
        """Fetch single audit log detail by ID."""
        stmt = select(AuditLog).options(selectinload(AuditLog.user)).where(AuditLog.id == log_id)
        res = await self.db.execute(stmt)
        log = res.scalars().first()
        if not log:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audit log entry not found.",
            )
        return self._to_response(log)

    async def generate_audit_logs_csv(
        self,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        module: Optional[str] = None,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> str:
        """Generate CSV export string for audit logs."""
        list_res = await self.list_audit_logs(
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            action=action,
            module=module,
            status_filter=status_filter,
            search=search,
            page=1,
            limit=10000,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Audit ID",
            "Date & Time",
            "User Name",
            "User Email",
            "Role",
            "Action",
            "Module",
            "Entity Type",
            "Entity ID",
            "IP Address",
            "HTTP Method",
            "Endpoint",
            "Status",
        ])

        for item in list_res.items:
            writer.writerow([
                item.id,
                item.created_at,
                item.user_name,
                item.user_email or "N/A",
                item.user_role,
                item.action,
                item.module,
                item.entity_type or "—",
                item.entity_id or "—",
                item.ip_address,
                item.request_method,
                item.endpoint,
                item.status,
            ])

        return output.getvalue()

    async def delete_audit_log(self, log_id: str) -> bool:
        """Delete a single audit log entry by ID."""
        stmt = select(AuditLog).where(AuditLog.id == log_id)
        res = await self.db.execute(stmt)
        log = res.scalars().first()
        if not log:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Audit log entry not found.",
            )
        await self.db.delete(log)
        await self.db.commit()
        return True

    async def bulk_delete_audit_logs(self, log_ids: List[str]) -> int:
        """Delete multiple audit log entries by their IDs."""
        if not log_ids:
            return 0
        del_stmt = delete(AuditLog).where(AuditLog.id.in_(log_ids))
        result = await self.db.execute(del_stmt)
        await self.db.commit()
        return result.rowcount or 0
