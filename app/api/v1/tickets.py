from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.ticket import CreateTicketPayload, SupportTicketResponse, TicketFeedbackPayload
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/support/tickets", tags=["Support Tickets"])


@router.get(
    "",
    response_model=list[SupportTicketResponse],
    summary="Get user's support tickets",
)
async def get_tickets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    return await service.get_user_tickets(current_user.id)


@router.post(
    "",
    response_model=SupportTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new support ticket",
)
async def create_ticket(
    payload: CreateTicketPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = CustomerService(db)
        return await service.create_ticket(current_user, payload)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{ticket_id}",
    response_model=SupportTicketResponse,
    summary="Get a single support ticket by ID",
)
async def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    ticket = await service.get_ticket_by_id(ticket_id, current_user.id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket


@router.get(
    "/{ticket_id}/related-order",
    summary="Get related order details for a support ticket",
)
async def get_ticket_related_order(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = CustomerService(db)
        return await service.get_ticket_related_order(ticket_id, current_user)
    except ValueError as e:
        msg = str(e)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in msg.lower() else status.HTTP_403_FORBIDDEN if "denied" in msg.lower() or "belong" in msg.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=msg)


@router.post(
    "/{ticket_id}/feedback",
    response_model=SupportTicketResponse,
    summary="Submit resolution feedback for a ticket",
)
async def submit_feedback(
    ticket_id: str,
    payload: TicketFeedbackPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    feedback_str = payload.feedback if hasattr(payload, "feedback") else str(payload)
    ticket = await service.submit_ticket_feedback(ticket_id, current_user.id, feedback_str)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found.")
    return ticket
