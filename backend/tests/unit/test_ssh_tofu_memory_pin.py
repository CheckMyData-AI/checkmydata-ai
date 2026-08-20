"""F-SSH-01 — `tofu` disabled itself when it could not write, and said so in a log line.

`connect_with_policy` used to answer an unwritable `known_hosts` by setting
`known_hosts=None` and connecting anyway — for that connection and every one after it. A
warning went to the log and the connection proceeded **unverified**, indefinitely.

The module's own closing branch reads:

    # F-SEC-4: fail closed — an unrecognised policy must never silently
    # disable verification.

Two branches above it, that is exactly what happened. A control that turns itself off and
logs about it is off; the log line is only the difference between finding out later and
never.

Fail-closed is not the fix either — it would break every SSH connection on a read-only
filesystem to protect a promise the operator never made. Instead the pin moves into
process memory: the first connect to a host in this process is unverified, which is what
trust-on-first-use *is*, and every later connect to that host is checked against the key
that first one presented. On Heroku, where the file is writable but the disk does not
survive a restart (AUD-0819-06), that is already the guarantee — so this is a downgrade
nowhere.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors import ssh_known_hosts as skh


class _Key:
    def __init__(self, blob: str):
        self._blob = blob

    def export_public_key(self) -> bytes:
        return f"ssh-ed25519 {self._blob} comment".encode()


def _conn(blob: str = "AAAAKEY1") -> MagicMock:
    c = MagicMock()
    c.get_server_host_key = MagicMock(return_value=_Key(blob))
    return c


@pytest.fixture(autouse=True)
def _clean_memory_pins():
    skh.reset_memory_pins()
    yield
    skh.reset_memory_pins()


@pytest.fixture
def unwritable(tmp_path, monkeypatch):
    """A known_hosts path this process cannot write — the trigger for the whole branch."""
    monkeypatch.setattr(skh.settings, "ssh_host_key_policy", "tofu")
    monkeypatch.setattr(skh.settings, "ssh_known_hosts_path", str(tmp_path / "kh"))
    monkeypatch.setattr(skh, "_ensure_known_hosts_file", lambda _p: False)


class TestItNoLongerConnectsUnverifiedForever:
    @pytest.mark.asyncio
    async def test_the_first_connection_pins_in_memory(self, unwritable):
        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn())):
            await skh.connect_with_policy({"host": "db.internal"})

        assert skh.memory_pinned_hosts() == {"db.internal"}

    @pytest.mark.asyncio
    async def test_a_second_connection_with_the_same_key_is_allowed(self, unwritable):
        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn())):
            await skh.connect_with_policy({"host": "db.internal"})
            await skh.connect_with_policy({"host": "db.internal"})

    @pytest.mark.asyncio
    async def test_a_changed_key_is_refused(self, unwritable):
        """The whole point. Before this, a man in the middle on connection two was
        indistinguishable from connection one."""
        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn("KEY1"))):
            await skh.connect_with_policy({"host": "db.internal"})

        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn("KEY2"))):
            with pytest.raises(skh.HostKeyChangedError, match="db.internal"):
                await skh.connect_with_policy({"host": "db.internal"})

    @pytest.mark.asyncio
    async def test_a_different_host_is_pinned_separately(self, unwritable):
        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn("KEY1"))):
            await skh.connect_with_policy({"host": "a.internal"})
        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn("KEY2"))):
            await skh.connect_with_policy({"host": "b.internal"})

        assert skh.memory_pinned_hosts() == {"a.internal", "b.internal"}

    @pytest.mark.asyncio
    async def test_a_connection_with_no_host_key_is_not_silently_trusted(self, unwritable):
        """`get_server_host_key()` returning None means there is nothing to compare a
        later connection against, so remembering the host would assert a check that
        cannot happen."""
        conn = MagicMock()
        conn.get_server_host_key = MagicMock(return_value=None)

        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=conn)):
            await skh.connect_with_policy({"host": "db.internal"})

        assert skh.memory_pinned_hosts() == set()


class TestTheWritablePathIsUnchanged:
    @pytest.mark.asyncio
    async def test_a_writable_file_still_pins_to_disk(self, tmp_path, monkeypatch):
        """The file is the durable pin and stays the primary one — memory is what
        happens when the filesystem refuses, not a replacement for it."""
        path = tmp_path / "kh"
        monkeypatch.setattr(skh.settings, "ssh_host_key_policy", "tofu")
        monkeypatch.setattr(skh.settings, "ssh_known_hosts_path", str(path))

        with patch.object(skh.asyncssh, "connect", new=AsyncMock(return_value=_conn())):
            await skh.connect_with_policy({"host": "db.internal"})

        assert "db.internal" in path.read_text()
        assert skh.memory_pinned_hosts() == set(), "the disk pin is the one that matters"

    @pytest.mark.asyncio
    async def test_strict_still_delegates_to_the_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(skh.settings, "ssh_host_key_policy", "strict")
        monkeypatch.setattr(skh.settings, "ssh_known_hosts_path", str(tmp_path / "kh"))
        connect = AsyncMock(return_value=_conn())

        with patch.object(skh.asyncssh, "connect", new=connect):
            await skh.connect_with_policy({"host": "db.internal"})

        assert connect.call_args.kwargs["known_hosts"] == str(tmp_path / "kh")

    @pytest.mark.asyncio
    async def test_disabled_is_still_an_explicit_opt_out(self, monkeypatch):
        """`disabled` means the operator said so. This finding is about the policy that
        turns itself off without being asked."""
        monkeypatch.setattr(skh.settings, "ssh_host_key_policy", "disabled")
        connect = AsyncMock(return_value=_conn())

        with patch.object(skh.asyncssh, "connect", new=connect):
            await skh.connect_with_policy({"host": "db.internal"})

        assert connect.call_args.kwargs["known_hosts"] is None
