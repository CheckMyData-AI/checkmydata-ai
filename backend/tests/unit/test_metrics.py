"""Tests for metrics recording and path normalization."""

from app.api.routes.metrics import _normalize_path, record_request


class TestNormalizePath:
    def test_uuid_replaced(self):
        path = "/api/projects/a1b2c3d4-e5f6-7890-abcd-ef1234567890/chat"
        assert _normalize_path(path) == "/api/projects/:id/chat"

    def test_multiple_uuids(self):
        uid1 = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        uid2 = "f1e2d3c4-b5a6-7890-1234-567890abcdef"
        path = f"/api/projects/{uid1}/conn/{uid2}"
        assert _normalize_path(path) == "/api/projects/:id/conn/:id"

    def test_no_uuid_unchanged(self):
        assert _normalize_path("/api/health") == "/api/health"


class TestRecordRequest:
    def test_basic_recording(self):
        record_request("/api/test-path", 12.5, is_error=False)

    def test_error_recording(self):
        record_request("/api/test-error", 50.0, is_error=True)
