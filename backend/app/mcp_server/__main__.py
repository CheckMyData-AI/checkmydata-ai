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
    parser = argparse.ArgumentParser(description="eSIM Database Agent MCP Server")
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

    from app.mcp_server.server import create_mcp_server

    mcp = create_mcp_server()

    run_kwargs: dict = {"transport": args.transport}
    if args.transport in ("sse", "streamable-http"):
        run_kwargs["host"] = args.host
        run_kwargs["port"] = args.port

    mcp.run(**run_kwargs)


if __name__ == "__main__":
    main()
