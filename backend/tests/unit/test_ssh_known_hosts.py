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
async def test_unknown_policy_fails_closed_to_strict(tmp_path):
    """F-SEC-4: an unrecognised policy must never disable verification."""
    path = str(tmp_path / "known_hosts")
    captured: dict = {}

    async def fake_connect(**kw):
        captured.update(kw)
        return MagicMock()

    with (
        patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "bogus"),
        patch.object(ssh_known_hosts.settings, "ssh_known_hosts_path", path),
        patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=fake_connect),
    ):
        await ssh_known_hosts.connect_with_policy(_kwargs())

    assert captured["known_hosts"] == path


@pytest.mark.asyncio
async def test_default_policy_is_tofu():
    """F-SEC-4: the shipped default must verify host keys (tofu), not disable."""
    from app.config import Settings

    assert Settings.model_fields["ssh_host_key_policy"].default == "tofu"
    with patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", ""):
        assert ssh_known_hosts._policy() == "tofu"


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


# ---------------------------------------------------------------------------
# F-SSH-05: the check-then-pin race does not reproduce, and now cannot appear
# ---------------------------------------------------------------------------


class TestFirstConnectPinIsAtomic:
    """The row reads "TOFU check-then-pin not atomic (concurrent first-connect race)".

    It does not reproduce. `_connect_with_memory_pin` awaits the connect and then runs
    read-key → compare → pin with **no `await` at all**, and `_host_key_blob` is a plain
    `def`. On one event loop a coroutine cannot be interleaved without an await, so the
    pair is atomic — two concurrent first-connects cannot both see "unpinned".

    The first two tests below passed against unmodified code, which is the evidence.
    They are kept as regression guards, and the third converts the property they rely
    on from *a fact that happens to hold* into *an invariant that fails loudly*: a
    future edit adding an await in that stretch — an async audit-log call, say — would
    open exactly the race the row describes, and nothing else would notice.
    """

    @staticmethod
    def _kw(host: str = "10.0.0.1") -> dict:
        return {"host": host, "port": 22, "username": "deploy"}

    @pytest.mark.asyncio
    async def test_the_second_concurrent_first_connect_is_compared_not_pinned(self):
        import asyncio

        ssh_known_hosts.reset_memory_pins()

        async def slow_connect(**kw):  # noqa: ARG001
            await asyncio.sleep(0.02)
            return MagicMock()

        # Two different host keys: whichever pins first wins, and the other must be
        # compared against that pin rather than quietly replacing it.
        blobs = iter(["ssh-ed25519 AAAA-A", "ssh-ed25519 AAAA-B"])

        with (
            patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "tofu"),
            patch.object(ssh_known_hosts, "_ensure_known_hosts_file", return_value=False),
            patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=slow_connect),
            patch.object(ssh_known_hosts, "_host_key_blob", side_effect=lambda c: next(blobs)),  # noqa: ARG005
        ):
            results = await asyncio.gather(
                ssh_known_hosts.connect_with_policy(self._kw()),
                ssh_known_hosts.connect_with_policy(self._kw()),
                return_exceptions=True,
            )

        changed = [r for r in results if isinstance(r, ssh_known_hosts.HostKeyChangedError)]
        assert len(changed) == 1, (
            "exactly one of two concurrent first-connects may pin; the other must be "
            f"compared against that pin and refused, got {results}"
        )
        assert len(ssh_known_hosts.memory_pinned_hosts()) == 1

    @pytest.mark.asyncio
    async def test_two_concurrent_connects_with_the_same_key_both_succeed(self):
        import asyncio

        ssh_known_hosts.reset_memory_pins()

        async def slow_connect(**kw):  # noqa: ARG001
            await asyncio.sleep(0.02)
            return MagicMock()

        with (
            patch.object(ssh_known_hosts.settings, "ssh_host_key_policy", "tofu"),
            patch.object(ssh_known_hosts, "_ensure_known_hosts_file", return_value=False),
            patch.object(ssh_known_hosts.asyncssh, "connect", side_effect=slow_connect),
            patch.object(ssh_known_hosts, "_host_key_blob", return_value="ssh-ed25519 same"),
        ):
            results = await asyncio.gather(
                ssh_known_hosts.connect_with_policy(self._kw()),
                ssh_known_hosts.connect_with_policy(self._kw()),
            )

        assert all(r is not None for r in results)
        assert len(ssh_known_hosts.memory_pinned_hosts()) == 1

    def test_no_await_may_appear_between_reading_the_pin_and_writing_it(self):
        """The atomicity above is a property of the code's shape, so assert the shape.

        Adding a lock instead would be complexity for a race that cannot happen; this
        costs nothing and fails the moment the precondition stops holding.
        """
        import ast
        import inspect

        from app.connectors import ssh_known_hosts as mod

        tree = ast.parse(inspect.getsource(mod))
        fn = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_connect_with_memory_pin"
        )
        idx = next(
            i
            for i, st in enumerate(fn.body)
            if isinstance(st, ast.Assign) and "_MEMORY_PINS" in ast.dump(st)
        )
        awaits = [
            n.lineno for st in fn.body[idx:] for n in ast.walk(st) if isinstance(n, ast.Await)
        ]
        assert not awaits, (
            f"an await at line(s) {awaits} sits between reading the memory pin and "
            "writing it — that opens the concurrent first-connect race F-SSH-05 "
            "describes. Serialize the section with a per-host lock if the await is "
            "genuinely needed."
        )
