"""Request-scoped runtime state for the MCP server.

``current_principal`` carries the authenticated principal resolved by the
HTTP auth middleware so tools read identity from the request context rather
than a process-wide env var (multi-tenant safety). ``*_trace_service`` is a
module-level holder the FastAPI lifespan populates when the MCP app is
mounted, so tools can persist traces without reaching into ``app.main``.
"""

from __future__ import annotations

from contextvars import ContextVar

# Principal dict shape: {"user_id": str, "email": str}.
current_principal: ContextVar[dict | None] = ContextVar("mcp_current_principal", default=None)

_trace_service: object | None = None


def set_trace_service(svc: object | None) -> None:
    global _trace_service  # noqa: PLW0603
    _trace_service = svc


def get_trace_service() -> object | None:
    return _trace_service
