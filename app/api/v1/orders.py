from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.order import OrderPayload, OrderResponse
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place a new order",
)
async def place_order(
    payload: OrderPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        service = CustomerService(db)
        return await service.place_order(current_user.id, payload)
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        await db.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "",
    response_model=list[OrderResponse],
    summary="Get authenticated user's order history",
)
async def get_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    return await service.get_user_orders(current_user.id, current_user.role)


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    summary="Get single order details by ID",
)
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    order = await service.get_order_by_id(order_id, current_user.id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
    return order


@router.get(
    "/{order_id}/invoice",
    summary="Get order invoice as HTML or S3 redirect",
)
async def get_order_invoice(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import HTMLResponse, RedirectResponse
    from app.services.invoice_service import InvoiceService
    from app.repositories.order_repository import OrderRepository
    
    order_repo = OrderRepository(db)
    order = await order_repo.get_by_id(order_id)
    
    if not order or (order.user_id != current_user.id and current_user.role not in ["admin", "superadmin"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    user_name = current_user.full_name or "Customer"
    user_email = current_user.email or ""

    if getattr(order, "invoice_url", None) and str(order.invoice_url).startswith("http"):
        return RedirectResponse(url=order.invoice_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    cloud_url = await InvoiceService.generate_and_upload_invoice(order, user_name, user_email)
    if cloud_url:
        order.invoice_url = cloud_url
        await db.commit()
    html = InvoiceService.generate_html_invoice(order, user_name, user_email)
    return HTMLResponse(content=html)


@router.get(
    "/{order_id}/pdf",
    summary="Download order invoice as a real PDF document",
)
async def get_order_invoice_pdf(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi.responses import StreamingResponse
    from app.services.pdf_report_service import PdfReportService
    from app.repositories.order_repository import OrderRepository
    
    order_repo = OrderRepository(db)
    order = await order_repo.get_by_id(order_id)
    
    if not order or (order.user_id != current_user.id and current_user.role not in ["admin", "superadmin"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")

    user_name = current_user.full_name or "Customer"
    user_email = current_user.email or ""

    pdf_buffer = PdfReportService.generate_invoice_pdf(order, user_name, user_email)
    filename = f"Invoice-{order.id}.pdf"
    
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


from app.schemas.order import OrderPayload, OrderResponse, OrderReturnPayload


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel an order",
)
async def cancel_order(
    order_id: str,
    payload: Optional[OrderReturnPayload] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    service = CustomerService(db)
    try:
        reason = payload.reason if payload else None
        order = await service.cancel_order(order_id, current_user.id, reason=reason)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
        return order
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


from fastapi import Request, Form, File, UploadFile
from app.schemas.return_request import ReturnRequestResponse
from app.services.return_service import ReturnService


@router.post(
    "/{order_id}/return",
    response_model=OrderResponse,
    summary="Submit return request for delivered order (within 30 minutes of delivery)",
)
async def return_order(
    order_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    reason = None
    description = None
    photo = None
    photo_url = None

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        reason = form.get("reason")
        description = form.get("description")
        photo_field = form.get("photo")
        if photo_field is not None and hasattr(photo_field, "filename") and bool(getattr(photo_field, "filename", None)):
            photo = photo_field
        elif isinstance(photo_field, str) and photo_field.strip():
            photo_url = photo_field.strip()
        photo_url_field = form.get("photo_url")
        if isinstance(photo_url_field, str) and photo_url_field.strip() and not photo:
            photo_url = photo_url_field.strip()

    elif "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                reason = body.get("reason")
                description = body.get("description")
                photo_url = body.get("photo_url")
        except Exception:
            pass

    clean_reason = str(reason or "")
    clean_desc = str(description or "")

    return_service = ReturnService(db)
    try:
        return_req = await return_service.create_return_request(
            order_id=order_id,
            user=current_user,
            reason=clean_reason,
            description=clean_desc,
            photo=photo,
            photo_url=photo_url,
        )
        # Fetch updated order response
        customer_service = CustomerService(db)
        order = await customer_service.order_repo.get_by_id(order_id)
        if not order:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found.")
        resp = customer_service._format_order_response(order)
        resp.return_request = ReturnRequestResponse.model_validate(return_req)
        return resp
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/{order_id}/return",
    response_model=ReturnRequestResponse,
    summary="Get return request details for an order",
)
async def get_order_return_request(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return_service = ReturnService(db)
    return_req = await return_service.get_return_request_by_order(order_id, current_user)
    if not return_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No return request found for this order."
        )
    return ReturnRequestResponse.model_validate(return_req)

