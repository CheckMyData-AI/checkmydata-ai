"""C7 / F-MCP-04: emit a startup WARNING when MCP is HTTP-mounted with
empty ``MCP_ALLOWED_HOSTS``.

The mounted transport's DNS-rebinding Host validation is opt-in (operators
self-host and may genuinely want it off), so we don't fail-closed — but
the silent state is the bug that lets a misconfigured deployment ship
without realising the protection is off.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

from app.mcp_server.server import create_mcp_server


class TestDnsRebindingStartupWarning:
    def test_warning_when_mount_enabled_without_allowed_hosts(self, caplog):
        """``mcp_mount_enabled=True`` + empty ``mcp_allowed_hosts`` must
        log a WARNING naming F-MCP-04 so ops engineers see it on boot."""
        with patch("app.mcp_server.server.settings") as mock_settings:
            mock_settings.mcp_mount_enabled = True
            mock_settings.mcp_allowed_hosts = []
            mock_settings.cors_origins = []
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.server"):
                create_mcp_server()

        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("MCP_ALLOWED_HOSTS" in r.message for r in warning_records), (
            "Expected a startup WARNING naming MCP_ALLOWED_HOSTS so an operator "
            "can grep their boot log and notice the protection is off."
        )
        assert any("F-MCP-04" in r.message for r in warning_records), (
            "Warning must cite the bug id (F-MCP-04) so the audit trail links back to the issue."
        )

    def test_no_warning_when_mount_disabled(self, caplog):
        """If the HTTP mount is off, the DNS-rebinding concern is moot
        (the standalone transport is env-bound + single-principal) — no
        warning should fire."""
        with patch("app.mcp_server.server.settings") as mock_settings:
            mock_settings.mcp_mount_enabled = False
            mock_settings.mcp_allowed_hosts = []
            mock_settings.cors_origins = []
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.server"):
                create_mcp_server()

        assert not any(
            "MCP_ALLOWED_HOSTS" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )

    def test_no_warning_when_mount_enabled_with_allowed_hosts(self, caplog):
        """When the operator has configured allowed hosts there's nothing
        to warn about — protection is on."""
        with patch("app.mcp_server.server.settings") as mock_settings:
            mock_settings.mcp_mount_enabled = True
            mock_settings.mcp_allowed_hosts = ["api.checkmydata.ai"]
            mock_settings.cors_origins = []
            with caplog.at_level(logging.WARNING, logger="app.mcp_server.server"):
                create_mcp_server()

        assert not any(
            "MCP_ALLOWED_HOSTS" in r.message and r.levelno == logging.WARNING
            for r in caplog.records
        )
