from typing import Optional, List
from sqlalchemy import select, func, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.user import User
from app.core.security import hash_password
from app.services.activity_log_service import log_admin_activity
from app.schemas.superadmin_admins import (
    AdminCreateRequest,
    AdminUpdateRequest,
    AdminStatusUpdateRequest,
    AdminPasswordUpdateRequest,
    AdminUserResponse,
    AdminListResponse,
)
from app.services.superadmin_notification_service import create_admin_management_notification


class SuperadminAdminsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _count_superadmins(self, exclude_id: Optional[str] = None) -> int:
        """Count active superadmin accounts in the database."""
        stmt = select(func.count(User.id)).where(
            User.role.in_(["superadmin", "super_admin"]),
            User.is_active == True,
        )
        if exclude_id:
            stmt = stmt.where(User.id != exclude_id)
        res = await self.db.execute(stmt)
        return res.scalar_one() or 0

    def _to_response(self, user: User) -> AdminUserResponse:
        return AdminUserResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            role=user.role,
            is_active=user.is_active,
            status="active" if user.is_active else "inactive",
            created_at=user.created_at.strftime("%d %b %Y, %I:%M %p") if user.created_at else "",
            last_login_at=user.last_login_at.strftime("%d %b %Y, %I:%M %p") if user.last_login_at else "Never",
        )

    async def register_admin(
        self, payload: AdminCreateRequest, current_superadmin: User
    ) -> AdminUserResponse:
        """Register a new administrator or superadmin account."""
        # Check duplicate email
        existing_res = await self.db.execute(select(User).where(User.email == payload.email))
        if existing_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An account with email '{payload.email}' already exists.",
            )

        hashed_pwd = hash_password(payload.password)

        from app.integrations.msg91 import normalize_phone
        clean_phone = normalize_phone(payload.phone) if payload.phone else None

        new_admin = User(
            full_name=payload.full_name.strip(),
            email=payload.email.lower().strip(),
            phone=clean_phone,
            hashed_password=hashed_pwd,
            role=payload.role.lower(),
            is_active=(payload.status.lower() == "active"),
            is_email_verified=True,
        )

        self.db.add(new_admin)
        await self.db.commit()
        await self.db.refresh(new_admin)

        # Audit log
        await log_admin_activity(
            db=self.db,
            admin_id=current_superadmin.id,
            action="CREATE_ADMIN",
            module="admin_management",
            description=f"Super Admin {current_superadmin.full_name} created new {new_admin.role.upper()} account '{new_admin.full_name}' ({new_admin.email}).",
        )

        # Superadmin notification
        await create_admin_management_notification(
            db=self.db,
            title=f"New {new_admin.role.capitalize()} Created",
            message=f"Account '{new_admin.full_name}' ({new_admin.email}) was registered with role {new_admin.role.upper()}.",
            severity="INFO",
            related_entity_id=new_admin.id,
            related_user_id=new_admin.id,
        )

        try:
            import asyncio
            from app.integrations.resend import resend_email
            asyncio.create_task(
                resend_email.send_superadmin_new_admin(
                    super_admin_email=current_superadmin.email,
                    super_admin_name=current_superadmin.full_name,
                    admin_name=new_admin.full_name,
                    admin_email=new_admin.email,
                    created_at=new_admin.created_at.strftime("%d %b %Y, %I:%M %p") if new_admin.created_at else "",
                )
            )
        except Exception:
            pass

        return self._to_response(new_admin)

    async def list_admins(
        self,
        search: Optional[str] = None,
        role: Optional[str] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        limit: int = 10,
    ) -> AdminListResponse:
        """Fetch paginated list of administrators."""
        stmt = select(User).where(User.role.in_(["admin", "superadmin", "super_admin"]))

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.phone.ilike(pattern),
                )
            )

        if role and role.lower() != "all":
            stmt = stmt.where(User.role == role.lower())

        if status_filter and status_filter.lower() != "all":
            is_act = (status_filter.lower() == "active")
            stmt = stmt.where(User.is_active == is_act)

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_res = await self.db.execute(count_stmt)
        total_count = total_res.scalar_one() or 0

        # Paginated results
        stmt = stmt.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit)
        users_res = await self.db.execute(stmt)
        users = users_res.scalars().all()

        items = [self._to_response(u) for u in users]

        return AdminListResponse(
            items=items,
            total=total_count,
            page=page,
            limit=limit,
        )

    async def get_admin_by_id(self, admin_id: str) -> AdminUserResponse:
        """Fetch administrator details by ID."""
        user = await self.db.get(User, admin_id)
        if not user or user.role not in ["admin", "superadmin", "super_admin"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator account not found.",
            )
        return self._to_response(user)

    async def update_admin(
        self, admin_id: str, payload: AdminUpdateRequest, current_superadmin: User
    ) -> AdminUserResponse:
        """Update administrator profile details."""
        user = await self.db.get(User, admin_id)
        if not user or user.role not in ["admin", "superadmin", "super_admin"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator account not found.",
            )

        # Duplicate email check
        if payload.email and payload.email.lower() != user.email:
            existing_res = await self.db.execute(
                select(User).where(User.email == payload.email.lower(), User.id != admin_id)
            )
            if existing_res.scalars().first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"An account with email '{payload.email}' already exists.",
                )
            user.email = payload.email.lower().strip()

        if payload.full_name:
            user.full_name = payload.full_name.strip()

        if payload.phone is not None:
            if payload.phone and str(payload.phone).strip():
                from app.integrations.msg91 import normalize_phone
                user.phone = normalize_phone(payload.phone)
            else:
                user.phone = None

        # Guardrail: Role Demotion Check
        if payload.role and payload.role != user.role:
            if user.role in ("superadmin", "super_admin") and payload.role == "admin":
                remaining_superadmins = await self._count_superadmins(exclude_id=user.id)
                if remaining_superadmins == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot demote the final remaining Super Admin account in the system.",
                    )
            user.role = payload.role

        if payload.status:
            new_is_active = (payload.status.lower() == "active")
            if user.role in ("superadmin", "super_admin") and not new_is_active and user.is_active:
                remaining_superadmins = await self._count_superadmins(exclude_id=user.id)
                if remaining_superadmins == 0:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot deactivate the final remaining Super Admin account in the system.",
                    )
            user.is_active = new_is_active

        await self.db.commit()
        await self.db.refresh(user)

        # Audit log
        await log_admin_activity(
            db=self.db,
            admin_id=current_superadmin.id,
            action="UPDATE_ADMIN",
            module="admin_management",
            description=f"Super Admin {current_superadmin.full_name} updated administrator profile for '{user.full_name}' ({user.email}).",
        )

        # Superadmin notification
        await create_admin_management_notification(
            db=self.db,
            title="Admin Profile Updated",
            message=f"Administrator '{user.full_name}' ({user.email}) profile details were updated.",
            severity="INFO",
            related_entity_id=user.id,
            related_user_id=user.id,
        )

        try:
            from datetime import datetime
            import asyncio
            from app.integrations.resend import resend_email
            asyncio.create_task(
                resend_email.send_superadmin_admin_updated(
                    super_admin_email=current_superadmin.email,
                    super_admin_name=current_superadmin.full_name,
                    admin_name=user.full_name,
                    admin_email=user.email,
                    updated_at=datetime.now().strftime("%d %b %Y, %I:%M %p"),
                )
            )
        except Exception:
            pass

        return self._to_response(user)

    async def update_admin_status(
        self, admin_id: str, payload: AdminStatusUpdateRequest, current_superadmin: User
    ) -> AdminUserResponse:
        """Activate or deactivate an administrator account."""
        user = await self.db.get(User, admin_id)
        if not user or user.role not in ["admin", "superadmin"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator account not found.",
            )

        new_is_active = (payload.status.lower() == "active")

        # Guardrail: Cannot deactivate last superadmin
        if user.role in ("superadmin", "super_admin") and not new_is_active and user.is_active:
            remaining_superadmins = await self._count_superadmins(exclude_id=user.id)
            if remaining_superadmins == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate the final remaining Super Admin account in the system.",
                )

        user.is_active = new_is_active
        await self.db.commit()
        await self.db.refresh(user)

        action_label = "activated" if new_is_active else "deactivated"

        # Audit log
        await log_admin_activity(
            db=self.db,
            admin_id=current_superadmin.id,
            action="CHANGE_STATUS_ADMIN",
            module="admin_management",
            description=f"Super Admin {current_superadmin.full_name} {action_label} administrator account '{user.full_name}' ({user.email}).",
        )

        # Superadmin notification
        await create_admin_management_notification(
            db=self.db,
            title=f"Admin Account {action_label.capitalize()}",
            message=f"Administrator account '{user.full_name}' ({user.email}) was {action_label}.",
            severity="WARNING" if not new_is_active else "INFO",
            related_entity_id=user.id,
            related_user_id=user.id,
        )

        try:
            from datetime import datetime
            import asyncio
            from app.integrations.resend import resend_email
            dt_str = datetime.now().strftime("%d %b %Y, %I:%M %p")
            if new_is_active:
                asyncio.create_task(
                    resend_email.send_superadmin_admin_activated(
                        super_admin_email=current_superadmin.email,
                        super_admin_name=current_superadmin.full_name,
                        admin_name=user.full_name,
                        admin_email=user.email,
                        activated_at=dt_str,
                    )
                )
            else:
                asyncio.create_task(
                    resend_email.send_superadmin_admin_deactivated(
                        super_admin_email=current_superadmin.email,
                        super_admin_name=current_superadmin.full_name,
                        admin_name=user.full_name,
                        admin_email=user.email,
                        deactivated_at=dt_str,
                    )
                )
        except Exception:
            pass

        return self._to_response(user)

    async def update_admin_password(
        self, admin_id: str, payload: AdminPasswordUpdateRequest, current_superadmin: User
    ) -> AdminUserResponse:
        """Securely update administrator password."""
        user = await self.db.get(User, admin_id)
        if not user or user.role not in ["admin", "superadmin"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator account not found.",
            )

        user.hashed_password = hash_password(payload.new_password)
        await self.db.commit()
        await self.db.refresh(user)

        # Audit log
        await log_admin_activity(
            db=self.db,
            admin_id=current_superadmin.id,
            action="RESET_PASSWORD_ADMIN",
            module="admin_management",
            description=f"Super Admin {current_superadmin.full_name} reset password for administrator account '{user.full_name}' ({user.email}).",
        )

        # Superadmin security notification
        from app.services.superadmin_notification_service import create_security_notification
        await create_security_notification(
            db=self.db,
            title="Admin Password Changed / Reset",
            message=f"Password for Administrator '{user.full_name}' ({user.email}) was reset by Super Admin.",
            severity="WARNING",
            related_entity_id=user.id,
            related_user_id=user.id,
        )

        try:
            from datetime import datetime
            import asyncio
            from app.integrations.resend import resend_email
            asyncio.create_task(
                resend_email.send_superadmin_admin_password_updated(
                    super_admin_email=current_superadmin.email,
                    super_admin_name=current_superadmin.full_name,
                    admin_name=user.full_name,
                    admin_email=user.email,
                    updated_at=datetime.now().strftime("%d %b %Y, %I:%M %p"),
                )
            )
        except Exception:
            pass

        return self._to_response(user)

    async def delete_admin(self, admin_id: str, current_superadmin: User) -> dict:
        """Delete an administrator account with security guardrails."""
        # Guardrail 1: Prevent self-deletion
        if current_superadmin.id == admin_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security Guardrail: Super Admin cannot delete their own active account.",
            )

        user = await self.db.get(User, admin_id)
        if not user or user.role not in ["admin", "superadmin", "super_admin"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Administrator account not found.",
            )

        # Guardrail 2: Prevent deleting last remaining superadmin
        if user.role in ("superadmin", "super_admin"):
            remaining_superadmins = await self._count_superadmins(exclude_id=user.id)
            if remaining_superadmins == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security Guardrail: Cannot delete the final remaining Super Admin account in the system.",
                )

        target_name = user.full_name
        target_email = user.email

        await self.db.delete(user)
        await self.db.commit()

        # Audit log
        await log_admin_activity(
            db=self.db,
            admin_id=current_superadmin.id,
            action="DELETE_ADMIN",
            module="admin_management",
            description=f"Super Admin {current_superadmin.full_name} deleted administrator account '{target_name}' ({target_email}).",
        )

        # Superadmin notification
        await create_admin_management_notification(
            db=self.db,
            title="Administrator Account Deleted",
            message=f"Administrator account '{target_name}' ({target_email}) was removed from the platform.",
            severity="WARNING",
            related_entity_id=admin_id,
        )

        return {"message": f"Administrator account '{target_name}' deleted successfully."}
