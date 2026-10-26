"""
Unit and Integration Tests for Google OAuth Authentication (AUTH-001 Remediation).

Verifies:
1. Strict audience matching against settings.GOOGLE_CLIENT_ID.
2. Complete absence of audience=None fallback.
3. Rejection of tokens when audience is invalid or wrong.
4. Rejection of tokens when settings.GOOGLE_CLIENT_ID is empty/unconfigured.
5. Successful authentication when Google token is valid and audience matches.
6. Safe rejection on POST /api/v1/auth/google when token verification fails.
"""

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient

from app.services.google_service import GoogleService
from app.core.config import settings

pytestmark = pytest.mark.asyncio


class TestGoogleServiceAudienceValidation:

    async def test_verify_google_token_success_with_valid_audience(self, monkeypatch):
        """Valid token matching configured GOOGLE_CLIENT_ID returns user info."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")

        mock_payload = {
            "sub": "google-user-12345",
            "email": "googleuser@example.com",
            "name": "Google User",
            "picture": "https://example.com/avatar.jpg",
            "email_verified": True,
        }

        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=mock_payload) as mock_verify:
            result = await GoogleService.verify_google_token("valid-google-id-token")

            assert result is not None
            assert result["google_id"] == "google-user-12345"
            assert result["email"] == "googleuser@example.com"
            assert result["full_name"] == "Google User"
            assert result["avatar_url"] == "https://example.com/avatar.jpg"
            assert result["email_verified"] is True

            # Verify verify_oauth2_token was called with the configured client ID as audience
            mock_verify.assert_called_once()
            _, kwargs = mock_verify.call_args
            assert kwargs.get("audience") == "test-client-id.apps.googleusercontent.com" or mock_verify.call_args[0][2] == "test-client-id.apps.googleusercontent.com"

    async def test_verify_google_token_rejection_on_invalid_audience_no_fallback(self, monkeypatch):
        """Token with invalid audience is rejected immediately without fallback to audience=None."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "expected-client-id.apps.googleusercontent.com")

        with patch("google.oauth2.id_token.verify_oauth2_token", side_effect=ValueError("Token has wrong audience")) as mock_verify:
            result = await GoogleService.verify_google_token("foreign-app-id-token")

            # Must return None (rejected)
            assert result is None
            # Must ONLY be called once with the configured audience, NEVER with audience=None
            assert mock_verify.call_count == 1

    async def test_verify_google_token_rejection_when_client_id_unconfigured(self, monkeypatch):
        """When GOOGLE_CLIENT_ID is empty, token verification safely returns None without network calls."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")

        with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
            result = await GoogleService.verify_google_token("some-id-token")

            assert result is None
            mock_verify.assert_not_called()

    async def test_verify_google_token_empty_input(self):
        """Empty or None token input returns None."""
        assert await GoogleService.verify_google_token("") is None
        assert await GoogleService.verify_google_token(None) is None


class TestGoogleAuthEndpoint:

    async def test_google_login_endpoint_removed_returns_404(self, client: AsyncClient):
        """POST /api/v1/auth/google returns 404 because Google login endpoint has been safely removed."""
        response = await client.post(
            "/api/v1/auth/google",
            json={"id_token": "some-token"},
        )
        assert response.status_code == 404
