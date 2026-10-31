"""
Isolated tests for WhatsApp Cloud API Webhook Integration.
Tests verification (GET) and incoming event handling (POST) with HMAC-SHA256 signature validation.
"""

import hashlib
import hmac
import json
import pytest
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.main import app
from app.middleware.csrf_middleware import CSRF_EXEMPT_PATHS
from app.api.v1.whatsapp_webhook import (
    verify_whatsapp_webhook,
    receive_whatsapp_webhook,
    verify_meta_signature,
)


def run_coro(coro):
    """
    Drive an asynchronous coroutine to completion synchronously without
    requiring Windows Proactor loopback sockets or network loop infrastructure.
    """
    stack = [coro]
    val = None
    while stack:
        current = stack[-1]
        try:
            val = current.send(val)
            if hasattr(val, "send"):
                stack.append(val)
                val = None
        except StopIteration as e:
            stack.pop()
            val = e.value
    return val


class MockRequest:
    """Mock FastAPI/Starlette Request providing raw body bytes."""

    def __init__(self, body_bytes: bytes):
        self._body = body_bytes

    async def body(self) -> bytes:
        return self._body


def generate_meta_signature(payload_bytes: bytes, secret: str) -> str:
    """Helper to compute X-Hub-Signature-256 header using HMAC-SHA256."""
    sig_hash = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig_hash}"


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture(autouse=True)
def setup_database():
    """Override conftest setup_database to bypass database operations."""
    yield


@pytest.fixture(autouse=True)
def configure_test_secrets(monkeypatch):
    """Configure isolated WhatsApp credentials for testing."""
    test_verify_token = "secure_test_verify_token_9876543210"
    test_app_secret = "meta_test_app_secret_abcdef123456"

    monkeypatch.setattr(settings, "WHATSAPP_VERIFY_TOKEN", test_verify_token)
    monkeypatch.setattr(settings, "META_APP_SECRET", test_app_secret)
    yield


# ==============================================================================
# Requirements 1 & 2: Valid Verification Token & Exact Challenge
# ==============================================================================

def test_webhook_verification_valid_token():
    """Requirement 1 & 2: Valid verification token returns HTTP 200 and matches exact challenge."""
    challenge_code = "1158201444"
    response = run_coro(verify_whatsapp_webhook(
        hub_mode="subscribe",
        hub_verify_token=settings.WHATSAPP_VERIFY_TOKEN,
        hub_challenge=challenge_code,
    ))

    assert isinstance(response, PlainTextResponse)
    assert response.status_code == 200
    assert response.body.decode("utf-8") == challenge_code


def test_webhook_verification_alphanumeric_challenge():
    """Verify alphanumeric challenge string is returned verbatim."""
    challenge_code = "challenge_alpha_numeric_xyz_123"
    response = run_coro(verify_whatsapp_webhook(
        hub_mode="subscribe",
        hub_verify_token=settings.WHATSAPP_VERIFY_TOKEN,
        hub_challenge=challenge_code,
    ))

    assert response.status_code == 200
    assert response.body.decode("utf-8") == challenge_code


# ==============================================================================
# Requirement 3: Invalid Verification Token
# ==============================================================================

def test_webhook_verification_invalid_token():
    """Requirement 3: Invalid verification token returns HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        run_coro(verify_whatsapp_webhook(
            hub_mode="subscribe",
            hub_verify_token="completely_incorrect_token",
            hub_challenge="1158201444",
        ))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Verification failed"


def test_webhook_verification_invalid_mode():
    """Requirement 3: Mode other than 'subscribe' returns HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        run_coro(verify_whatsapp_webhook(
            hub_mode="unsubscribe",
            hub_verify_token=settings.WHATSAPP_VERIFY_TOKEN,
            hub_challenge="1158201444",
        ))

    assert exc_info.value.status_code == 403


# ==============================================================================
# Requirement 4: Missing Verification Parameters
# ==============================================================================

def test_webhook_verification_missing_mode():
    """Requirement 4: Missing hub.mode returns HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        run_coro(verify_whatsapp_webhook(
            hub_mode=None,
            hub_verify_token=settings.WHATSAPP_VERIFY_TOKEN,
            hub_challenge="1158201444",
        ))

    assert exc_info.value.status_code == 403


def test_webhook_verification_missing_token():
    """Requirement 4: Missing hub.verify_token returns HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        run_coro(verify_whatsapp_webhook(
            hub_mode="subscribe",
            hub_verify_token=None,
            hub_challenge="1158201444",
        ))

    assert exc_info.value.status_code == 403


def test_webhook_verification_missing_challenge():
    """Requirement 4: Missing hub.challenge returns HTTP 403."""
    with pytest.raises(HTTPException) as exc_info:
        run_coro(verify_whatsapp_webhook(
            hub_mode="subscribe",
            hub_verify_token=settings.WHATSAPP_VERIFY_TOKEN,
            hub_challenge=None,
        ))

    assert exc_info.value.status_code == 403


# ==============================================================================
# Requirement 5: Valid POST Payload with Valid Signature
# ==============================================================================

def test_webhook_post_valid_message_payload():
    """Requirement 5: Valid POST payload with valid HMAC-SHA256 signature is accepted."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "100609346426084",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550239999",
                                "phone_number_id": "100609346426084",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": "Customer Name"},
                                    "wa_id": "919999999999",
                                }
                            ],
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "wamid.HBgLMTU1NTAyMzk5OTkVAgASGBIA",
                                    "timestamp": "1672531199",
                                    "text": {"body": "Hello Chovique!"},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    valid_sig = generate_meta_signature(payload_bytes, settings.META_APP_SECRET)

    req = MockRequest(payload_bytes)
    result = run_coro(receive_whatsapp_webhook(req, valid_sig))

    assert result == {"status": "ok"}


def test_webhook_post_valid_status_payload():
    """Requirement 5: Valid status notification payload (delivered/read) is accepted."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "100609346426084",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550239999",
                                "phone_number_id": "100609346426084",
                            },
                            "statuses": [
                                {
                                    "id": "wamid.HBgLMTU1NTAyMzk5OTkVAgASGBIA",
                                    "status": "delivered",
                                    "timestamp": "1672531200",
                                    "recipient_id": "919999999999",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(payload).encode("utf-8")
    valid_sig = generate_meta_signature(payload_bytes, settings.META_APP_SECRET)

    req = MockRequest(payload_bytes)
    result = run_coro(receive_whatsapp_webhook(req, valid_sig))

    assert result == {"status": "ok"}


# ==============================================================================
# Requirement 6: Invalid Signature Rejected
# ==============================================================================

def test_webhook_post_missing_signature():
    """Requirement 6: Missing signature header is rejected with HTTP 403."""
    payload = {"object": "whatsapp_business_account", "entry": []}
    payload_bytes = json.dumps(payload).encode("utf-8")

    req = MockRequest(payload_bytes)
    with pytest.raises(HTTPException) as exc_info:
        run_coro(receive_whatsapp_webhook(req, None))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Invalid signature"


def test_webhook_post_tampered_payload_rejected():
    """Requirement 6: Tampered payload with mismatched signature is rejected with HTTP 403."""
    payload_original = json.dumps({"key": "original"}).encode("utf-8")
    sig = generate_meta_signature(payload_original, settings.META_APP_SECRET)

    # Tampered payload sent with original signature
    payload_tampered = json.dumps({"key": "tampered"}).encode("utf-8")
    req = MockRequest(payload_tampered)

    with pytest.raises(HTTPException) as exc_info:
        run_coro(receive_whatsapp_webhook(req, sig))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Invalid signature"


def test_webhook_post_malformed_signature_format():
    """Requirement 6: Signature missing 'sha256=' prefix is rejected with HTTP 403."""
    payload_bytes = json.dumps({"key": "value"}).encode("utf-8")
    raw_hash = hmac.new(
        key=settings.META_APP_SECRET.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    req = MockRequest(payload_bytes)
    with pytest.raises(HTTPException) as exc_info:
        run_coro(receive_whatsapp_webhook(req, raw_hash))  # missing 'sha256='

    assert exc_info.value.status_code == 403


# ==============================================================================
# Requirement 7: Malformed JSON Handled Safely
# ==============================================================================

def test_webhook_post_malformed_json_syntax():
    """Requirement 7: Malformed JSON syntax is safely rejected with HTTP 400."""
    malformed_raw = b'{"object": "whatsapp_business_account", "entry": [broken json'
    sig = generate_meta_signature(malformed_raw, settings.META_APP_SECRET)

    req = MockRequest(malformed_raw)
    with pytest.raises(HTTPException) as exc_info:
        run_coro(receive_whatsapp_webhook(req, sig))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Malformed JSON payload"


def test_webhook_post_non_dict_json():
    """Requirement 7: Valid JSON that is not an object (e.g. array) is rejected with HTTP 400."""
    non_dict_raw = b'["not", "a", "json", "object"]'
    sig = generate_meta_signature(non_dict_raw, settings.META_APP_SECRET)

    req = MockRequest(non_dict_raw)
    with pytest.raises(HTTPException) as exc_info:
        run_coro(receive_whatsapp_webhook(req, sig))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Malformed JSON payload"


# ==============================================================================
# Router Registration & CSRF Exemption Verification
# ==============================================================================

def test_router_registered_in_fastapi_app():
    """Verify that both /webhooks/whatsapp and /api/v1/webhooks/whatsapp routes exist on app."""
    route_paths = [getattr(r, "path", "") for r in app.routes]
    assert "/webhooks/whatsapp" in route_paths
    assert "/api/v1/webhooks/whatsapp" in route_paths


def test_csrf_exemptions_active():
    """Verify that WhatsApp webhook paths are registered in CSRF_EXEMPT_PATHS."""
    assert "/webhooks/whatsapp" in CSRF_EXEMPT_PATHS
    assert "/api/v1/webhooks/whatsapp" in CSRF_EXEMPT_PATHS
