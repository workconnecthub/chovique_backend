"""
WhatsApp Cloud API Webhook Integration for Chovique Backend.

Provides:
- GET /webhooks/whatsapp: Meta verification challenge handler
- POST /webhooks/whatsapp: Incoming webhook event handler with HMAC-SHA256 signature validation
"""

import hashlib
import hmac
import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.middleware.csrf_middleware import CSRF_EXEMPT_PATHS

# Ensure webhook paths are exempt from CSRF token validation
CSRF_EXEMPT_PATHS.add("/webhooks/whatsapp")
CSRF_EXEMPT_PATHS.add("/api/v1/webhooks/whatsapp")

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WhatsApp Webhook"])


def verify_meta_signature(body: bytes, signature_header: Optional[str], secret: str) -> bool:
    """
    Validate the X-Hub-Signature-256 header sent by Meta using HMAC-SHA256.
    Header format: sha256=<64-char-hex-digest>
    """
    if not signature_header or not secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    expected_header = f"sha256={expected_hash}"

    return secrets.compare_digest(signature_header, expected_header)


@router.get("/webhooks/whatsapp", summary="WhatsApp Webhook Verification")
@router.get("/api/v1/webhooks/whatsapp", include_in_schema=False)
async def verify_whatsapp_webhook(
    hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """
    Handle Meta WhatsApp Cloud API webhook verification requests.
    Validates hub.mode == 'subscribe' and hub.verify_token == WHATSAPP_VERIFY_TOKEN.
    Returns the exact challenge string as plain text with HTTP 200, or HTTP 403.
    """
    expected_token = settings.WHATSAPP_VERIFY_TOKEN

    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and expected_token
        and secrets.compare_digest(hub_verify_token, expected_token)
    ):
        if hub_challenge is not None:
            return PlainTextResponse(content=str(hub_challenge), status_code=status.HTTP_200_OK)

    logger.warning(
        "WhatsApp webhook verification failed. mode=%s, token_provided=%s",
        hub_mode,
        bool(hub_verify_token),
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification failed",
    )


@router.post("/webhooks/whatsapp", summary="WhatsApp Webhook Event Receiver")
@router.post("/api/v1/webhooks/whatsapp", include_in_schema=False)
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(default=None, alias="X-Hub-Signature-256"),
):
    """
    Handle incoming Meta WhatsApp Cloud API webhook notifications.
    Validates X-Hub-Signature-256 using HMAC-SHA256 and META_APP_SECRET.
    Parses JSON safely and logs events without recording any sensitive customer details.
    """
    body_bytes = await request.body()

    # 1. Validate signature using Meta App Secret
    if not settings.META_APP_SECRET:
        logger.error("WhatsApp webhook rejected: META_APP_SECRET is not configured.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook secret not configured",
        )

    if not verify_meta_signature(body_bytes, x_hub_signature_256, settings.META_APP_SECRET):
        logger.warning("WhatsApp webhook rejected: invalid or missing X-Hub-Signature-256.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )

    # 2. Parse JSON payload safely
    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a JSON object")
    except Exception as exc:
        logger.warning("WhatsApp webhook malformed JSON: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON payload",
        )

    # 3. Process events safely without logging sensitive customer data
    obj = payload.get("object")
    entries = payload.get("entry")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("id")
            changes = entry.get("changes")
            if isinstance(changes, list):
                for change in changes:
                    if not isinstance(change, dict):
                        continue
                    field = change.get("field")
                    value = change.get("value")
                    if isinstance(value, dict):
                        messages = value.get("messages")
                        statuses = value.get("statuses")
                        if messages and isinstance(messages, list):
                            logger.info(
                                "WhatsApp webhook: received %d message event(s) for entry %s",
                                len(messages),
                                entry_id,
                            )
                        if statuses and isinstance(statuses, list):
                            logger.info(
                                "WhatsApp webhook: received %d status notification(s) for entry %s",
                                len(statuses),
                                entry_id,
                            )
    else:
        logger.info("WhatsApp webhook received event for object: %s", obj)

    return {"status": "ok"}

