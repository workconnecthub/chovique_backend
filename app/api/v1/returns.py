import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_admin, get_db
from app.models.user import User
from app.schemas.return_request import (
    CreateReturnPayload,
    UpdateReturnStatusPayload,
    ReturnRequestResponse,
    ReturnPolicyResponse,
)
from app.services.return_service import ReturnService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/returns", tags=["Returns"])
admin_router = APIRouter(prefix="/admin/returns", tags=["Admin Returns"])


# ==========================================================
# Policy & Customer Endpoints
# ==========================================================

@router.get(
    "/policy",
    response_model=ReturnPolicyResponse,
    summary="Get current return policy configuration",
)
async def get_return_policy(
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    policy = await service.get_return_policy()
    return ReturnPolicyResponse(**policy)


@router.get(
    "",
    response_model=List[ReturnRequestResponse],
    summary="Get authenticated customer's return requests",
)
async def get_my_returns(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    items = await service.get_user_return_requests(current_user.id)
    return [ReturnRequestResponse.model_validate(item) for item in items]


@router.get(
    "/{return_id}",
    response_model=ReturnRequestResponse,
    summary="Get return request details by ID",
)
async def get_return_by_id(
    return_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    item = await service.get_return_request_by_id(return_id, current_user)
    return ReturnRequestResponse.model_validate(item)


# ==========================================================
# Support / Admin Endpoints
# ==========================================================

@admin_router.get(
    "",
    response_model=List[ReturnRequestResponse],
    summary="List all return requests for support/admin review",
)
async def list_all_returns(
    admin_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    items = await service.get_all_return_requests()
    return [ReturnRequestResponse.model_validate(item) for item in items]


@admin_router.get(
    "/{return_id}",
    response_model=ReturnRequestResponse,
    summary="Get return request details by ID (Admin)",
)
async def get_admin_return_by_id(
    return_id: str,
    admin_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    item = await service.get_return_request_by_id(return_id, admin_user)
    return ReturnRequestResponse.model_validate(item)


@admin_router.put(
    "/{return_id}/status",
    response_model=ReturnRequestResponse,
    summary="Update return request status (Admin/Support Team)",
)
async def update_return_status(
    return_id: str,
    payload: UpdateReturnStatusPayload,
    admin_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ReturnService(db)
    updated = await service.update_return_status(
        return_id=return_id,
        new_status=payload.status,
        admin_notes=payload.admin_notes,
        admin_user=admin_user,
    )
    return ReturnRequestResponse.model_validate(updated)
