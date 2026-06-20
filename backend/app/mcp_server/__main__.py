"""CLI entry point for the MCP server.

Usage::

    # stdio transport (default — for Claude Desktop, Cursor, etc.)
    python -m app.mcp_server

    # SSE transport (for HTTP-based clients)
    python -m app.mcp_server --transport sse --host 127.0.0.1 --port 8100

    # streamable-http transport
    python -m app.mcp_server --transport streamable-http --port 8100
"""

from __future__ import annotations

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(description="CheckMyData.ai MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help=(
            "MCP transport mode. 'stdio' (default) for local clients "
            "(Claude Desktop, Cursor); 'streamable-http' for remote / "
            "multi-client deployments; 'sse' is legacy and only kept "
            "for older clients."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE/HTTP transport")
    parser.add_argument("--port", type=int, default=8100, help="Port for SSE/HTTP transport")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    import os

    from app.config import settings
    from app.services.mcp_key_service import TOKEN_PREFIX

    # T-SEC-1: the MCP surface is off by default. Refuse to start unless an
    # operator has explicitly enabled it. At runtime, every tool call still
    # has to resolve to a real platform user — either through a per-user
    # `cmd_mcp_…` token (preferred) or the legacy server-key + MCP_API_KEY_USER_ID
    # binding. We accept either path here so a multi-tenant deployment can
    # run without the server-key + bound-user combo.
    if not settings.mcp_enabled:
        raise SystemExit(
            "MCP server is disabled. Set MCP_ENABLED=true and supply credentials "
            "(per-user `cmd_mcp_…` token via CHECKMYDATA_API_KEY, or legacy "
            "server-level CHECKMYDATA_API_KEY + MCP_API_KEY_USER_ID)."
        )

    candidate_key = os.environ.get("CHECKMYDATA_API_KEY") or os.environ.get("MCP_API_KEY") or ""
    is_personal_token = candidate_key.startswith(TOKEN_PREFIX)
    if not is_personal_token and not settings.mcp_api_key_user_id:
        raise SystemExit(
            "MCP server is misconfigured. Either set CHECKMYDATA_API_KEY to a "
            f"per-user '{TOKEN_PREFIX}…' token, or set MCP_API_KEY_USER_ID so the "
            "server-level API key is bound to a real platform user."
        )

    from app.mcp_server.server import create_mcp_server

    mcp = create_mcp_server()

    run_kwargs: dict = {"transport": args.transport}
    if args.transport in ("sse", "streamable-http"):
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port

    mcp.run(**run_kwargs)


if __name__ == "__main__":
    main()
