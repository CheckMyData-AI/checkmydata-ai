"""Unit tests for the SSH host-key verification policy (R1-2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.connectors import ssh_known_hosts


def _kwargs(host: str = "bastion.example.com") -> dict:
    return {"host": host, "port": 22, "username": "deploy"}


@pytest.mark.asyncio
async def test_disabled_policy_sets_known_hosts_none():
    captured: dict = {}

    async def fake_connect(**kw):
        captured.update(kw)
        return MagicMock()

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "disabled"),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs())

    assert captured["known_hosts"] is None


@pytest.mark.asyncio
async def test_strict_policy_uses_known_hosts_path(tmp_path):
    path = str(tmp_path / "known_hosts")
    captured: dict = {}

    async def fake_connect(**kw):
        captured.update(kw)
        return MagicMock()

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "strict"),
        patch.object(ssh_known_hosts.settings, "ssh_known_hosts_path", path),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs())

    assert captured["known_hosts"] == path


@pytest.mark.asyncio
async def test_tofu_first_use_pins_then_verifies(tmp_path):
    path = str(tmp_path / "known_hosts")
    host = "bastion.example.com"

    # A fake server host key whose public form is "ssh-ed25519 AAAA...".
    host_key = MagicMock()
    host_key.export_public_key.return_value = b"ssh-ed25519 AAAAC3Nz comment"

    calls: list = []

    async def fake_connect(**kw):
        calls.append(kw.get("known_hosts"))
        conn = MagicMock()
        conn.get_server_host_key.return_value = host_key
        return conn

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "tofu"),
        patch.object(ssh_known_hosts.settings, "ssh_known_hosts_path", path),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        # First use: host not pinned => connect unverified, then pin.
        await ssh_known_hosts.connect_with_policy(_kwargs(host))
        assert calls[-1] is None  # unverified first contact
        assert ssh_known_hosts._host_is_pinned(path, host) is True

        # Second use: host now pinned => verify against the file.
        await ssh_known_hosts.connect_with_policy(_kwargs(host))
        assert calls[-1] == path


@pytest.mark.asyncio
async def test_tofu_falls_back_when_path_unwritable():
    captured: dict = {}

    async def fake_connect(**kw):
        captured.update(kw)
        return MagicMock()

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "tofu"),
        patch.object(ssh_known_hosts, "_ensure_known_hosts_file", return_value=False),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs())

    assert captured["known_hosts"] is None


@pytest.mark.asyncio
async def test_unknown_policy_defaults_to_disabled():
    captured: dict = {}

    async def fake_connect(**kw):
        captured.update(kw)
        return MagicMock()

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "bogus"),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs())

    assert captured["known_hosts"] is None


@pytest.mark.asyncio
async def test_timeout_is_applied():
    async def slow_connect(**kw):
        import asyncio

        await asyncio.sleep(5)

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "disabled"),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=slow_connect),
        pytest.raises((TimeoutError, Exception)),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs(), timeout=0.05)
