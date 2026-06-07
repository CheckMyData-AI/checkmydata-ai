"""Unit tests for the browser session + CSRF cookie helpers (T-SEC-3).

Covers the split-domain regression: the session/CSRF cookies must carry the
configured parent ``Domain`` so a SPA on a different subdomain can read the
non-httpOnly CSRF cookie, and clearing must expire both the configured-domain
and legacy host-only scopes.
"""

from fastapi import Response

from app.core import auth_cookies
from app.core.auth_cookies import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    clear_session_cookies,
    set_session_cookies,
)


def _set_cookie_headers(response: Response) -> list[str]:
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


def _lines_for(headers: list[str], name: str) -> list[str]:
    return [h for h in headers if h.startswith(f"{name}=")]


class TestSetSessionCookies:
    def test_includes_domain_when_configured(self, monkeypatch):
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_domain", ".example.com")
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_secure", True)
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_samesite", "lax")

        resp = Response()
        set_session_cookies(resp, "jwt-token-value")
        headers = _set_cookie_headers(resp)

        session = _lines_for(headers, SESSION_COOKIE)
        csrf = _lines_for(headers, CSRF_COOKIE)
        assert session and csrf
        assert "Domain=.example.com" in session[0]
        assert "Domain=.example.com" in csrf[0]
        # Session cookie is hidden from JS; CSRF cookie must be readable.
        assert "HttpOnly" in session[0]
        assert "HttpOnly" not in csrf[0]
        assert "Secure" in session[0]

    def test_host_only_when_domain_empty(self, monkeypatch):
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_domain", "")
        resp = Response()
        set_session_cookies(resp, "jwt-token-value")
        headers = _set_cookie_headers(resp)
        assert headers
        assert all("Domain=" not in h for h in headers)


class TestClearSessionCookies:
    def test_clears_both_domain_and_host_only_scopes(self, monkeypatch):
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_domain", ".example.com")
        resp = Response()
        clear_session_cookies(resp)
        headers = _set_cookie_headers(resp)

        for name in (SESSION_COOKIE, CSRF_COOKIE):
            lines = _lines_for(headers, name)
            # One deletion scoped to the parent domain, one host-only.
            assert any("Domain=.example.com" in line for line in lines)
            assert any("Domain=" not in line for line in lines)
            # All deletions expire the cookie immediately.
            assert all("Max-Age=0" in line or "max-age=0" in line.lower() for line in lines)

    def test_host_only_only_when_domain_empty(self, monkeypatch):
        monkeypatch.setattr(auth_cookies.settings, "auth_cookie_domain", "")
        resp = Response()
        clear_session_cookies(resp)
        headers = _set_cookie_headers(resp)

        # Domain + host-only scopes collapse to a single host-only deletion each.
        assert len(_lines_for(headers, SESSION_COOKIE)) == 1
        assert len(_lines_for(headers, CSRF_COOKIE)) == 1
        assert all("Domain=" not in h for h in headers)
