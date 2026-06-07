import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestSecurityHeaders:
    def test_baseline_headers_present(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
        assert "Permissions-Policy" in resp.headers

    def test_csp_header_present_by_default(self, client):
        resp = client.get("/api/health")
        assert "Content-Security-Policy" in resp.headers
        csp = resp.headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp
        # Google Identity must stay allowlisted so login is not broken.
        assert "https://accounts.google.com" in csp
        # Report-only header must not also be emitted when enforcing.
        assert "Content-Security-Policy-Report-Only" not in resp.headers

    def test_hsts_emitted_over_https(self, client):
        # Simulate the Heroku/router forwarded-proto so the app treats the
        # request as HTTPS.
        resp = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
        assert "Strict-Transport-Security" in resp.headers
        hsts = resp.headers["Strict-Transport-Security"]
        assert "max-age=" in hsts
        assert "includeSubDomains" in hsts

    def test_hsts_absent_over_plain_http(self, client):
        resp = client.get("/api/health")
        # TestClient requests are http with no forwarded-proto -> no HSTS.
        assert "Strict-Transport-Security" not in resp.headers


class TestSecurityHeaderConfig:
    def test_report_only_mode_switches_header_name(self):
        """When report-only is enabled, the policy ships under the
        ...-Report-Only header so violations are logged but not blocked."""
        import app.config as config_module

        original_ro = config_module.settings.security_csp_report_only
        config_module.settings.security_csp_report_only = True
        try:
            reload_client = TestClient(app)
            resp = reload_client.get("/api/health")
            assert "Content-Security-Policy-Report-Only" in resp.headers
            assert "Content-Security-Policy" not in resp.headers
        finally:
            config_module.settings.security_csp_report_only = original_ro

    def test_csp_can_be_disabled(self):
        import app.config as config_module

        original = config_module.settings.security_csp_enabled
        config_module.settings.security_csp_enabled = False
        try:
            resp = TestClient(app).get("/api/health")
            assert "Content-Security-Policy" not in resp.headers
        finally:
            config_module.settings.security_csp_enabled = original
