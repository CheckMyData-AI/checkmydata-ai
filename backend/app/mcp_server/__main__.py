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
        help="MCP transport mode (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for SSE/HTTP transport")
    parser.add_argument("--port", type=int, default=8100, help="Port for SSE/HTTP transport")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    from app.config import settings

    # T-SEC-1: the MCP surface is off by default. Refuse to start unless an
    # operator has explicitly enabled it AND configured the user binding, so a
    # misconfigured deployment can never expose unauthenticated tools.
    if not settings.mcp_enabled:
        raise SystemExit(
            "MCP server is disabled. Set MCP_ENABLED=true (and MCP_API_KEY_USER_ID "
            "+ CHECKMYDATA_API_KEY) to run it."
        )
    if not settings.mcp_api_key_user_id:
        raise SystemExit(
            "MCP_API_KEY_USER_ID must be set so MCP tool calls are scoped to a real user."
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
