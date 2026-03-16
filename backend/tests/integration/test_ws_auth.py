"""Unit tests for WebSocket authentication logic in the chat endpoint."""

from app.services.auth_service import AuthService


class TestWebSocketAuth:
    """Verify the token validation logic used by the WS handler."""

    def test_valid_token_decodes(self):
        auth = AuthService()
        token = auth.create_token("user-123", "test@test.com")
        payload = auth.decode_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@test.com"

    def test_invalid_token_returns_none(self):
        auth = AuthService()
        payload = auth.decode_token("garbage-token")
        assert payload is None

    def test_empty_token_returns_none(self):
        auth = AuthService()
        payload = auth.decode_token("")
        assert payload is None

    def test_tampered_token_returns_none(self):
        auth = AuthService()
        token = auth.create_token("user-123", "test@test.com")
        tampered = token[:-5] + "XXXXX"
        payload = auth.decode_token(tampered)
        assert payload is None
