"""SSH host-key verification policy (R1-2).

Historically every SSH connection passed ``known_hosts=None`` to asyncssh,
which disables host-key verification entirely and leaves tunnels open to
man-in-the-middle attacks. This module centralises a configurable policy so
all three SSH call sites (tunnel, exec, and the connection_service liveness
test) behave consistently.

Policies (``settings.ssh_host_key_policy``):

* ``"disabled"`` — no verification (``known_hosts=None``). Explicit, logged,
  non-production-only override (F-SEC-4).
* ``"strict"`` — verify against ``settings.ssh_known_hosts_path``; unknown or
  changed host keys are rejected. The file must be pre-populated.
* ``"tofu"`` — trust-on-first-use. The first connection to an unseen host
  pins its key into the known_hosts file; every later connection is verified
  against the pinned key (so a *changed* key is rejected). asyncssh has no
  native first-use pinning, so :func:`connect_with_policy` implements it by
  pinning the server key after the first (unverified) handshake.

Call sites should build their ``connect_kwargs`` *without* a ``known_hosts``
entry and route through :func:`connect_with_policy`, which applies the policy
and returns a live connection.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

import asyncssh

from app.config import settings

logger = logging.getLogger(__name__)


def _policy() -> str:
    # F-SEC-4: fail towards verification — an unset/blank policy means "tofu".
    return (settings.ssh_host_key_policy or "tofu").strip().lower()


#: Path prefixes the OS is free to empty between process lifetimes. A TOFU store
#: living under one of these re-runs "first use" after every restart, so it pins
#: whatever key it is offered instead of verifying against what it pinned before.
_EPHEMERAL_PREFIXES = ("/tmp/", "/var/tmp/", "/private/tmp/", "/private/var/tmp/", "/dev/shm/")

_durability_warned = False


def known_hosts_is_ephemeral(path: str) -> bool:
    """Whether *path* sits on storage the OS may empty between restarts.

    A blank path is a different failure — there is nothing to write to — and this
    question does not apply to it, so it is not guessed at either way.
    """
    if not path:
        return False
    normalized = os.path.normpath(path)
    if not normalized.endswith("/"):
        normalized += "/"
    return normalized.startswith(_EPHEMERAL_PREFIXES)


def reset_durability_warning() -> None:
    """Test seam: forget that the durability warning was already emitted."""
    global _durability_warned  # noqa: PLW0603
    _durability_warned = False


def warn_if_known_hosts_ephemeral() -> None:
    """Say once that ``tofu`` cannot keep its promise on this host (AUD-0819-06).

    ``config.py`` describes ``tofu`` as pinning on first connect and verifying
    thereafter, "a *changed* key is rejected". That holds only while the store
    survives. On Heroku — the primary deploy target — ``ssh_known_hosts_path``
    defaults under ``/tmp``, and restarts are routine, so first use runs again on
    every boot and the rejection never happens. Until the pins live somewhere
    durable (docs/adr/0002-ssh-host-key-store.md) the least we owe an operator is
    to name it rather than let the config's promise stand unqualified.

    ``disabled`` is excluded on purpose: it already warns per connection, and a
    second warning beside it only dilutes the one that matters.
    """
    global _durability_warned  # noqa: PLW0603
    if _durability_warned:
        return
    policy = _policy()
    if policy not in ("tofu", "strict"):
        return
    path = settings.ssh_known_hosts_path
    if not known_hosts_is_ephemeral(path):
        return
    _durability_warned = True
    logger.warning(
        "SSH host-key store %r is on ephemeral storage: the pins do not survive a "
        "restart, so ssh_host_key_policy=%s re-runs first use on every boot and "
        "accepts whatever key is offered instead of rejecting a changed one. Point "
        "SSH_KNOWN_HOSTS_PATH at durable storage, or treat host-key verification as "
        "unavailable on this host.",
        path,
        policy,
    )


class HostKeyChangedError(Exception):
    """A host presented a different key than the one this process pinned (F-SSH-01)."""


#: host -> the public key blob this process saw first. Used only when the known_hosts
#: file cannot be written; the file is the durable pin and stays the primary one.
_MEMORY_PINS: dict[str, str] = {}


def memory_pinned_hosts() -> set[str]:
    """Hosts pinned in this process's memory. For tests and diagnostics."""
    return set(_MEMORY_PINS)


def reset_memory_pins() -> None:
    """Forget every in-memory pin. For tests."""
    _MEMORY_PINS.clear()


def _host_key_blob(conn: asyncssh.SSHClientConnection) -> str | None:
    """The connection's server host key as ``"keytype base64"``, or None if absent."""
    try:
        host_key = conn.get_server_host_key()
        if host_key is None:
            return None
        parts = host_key.export_public_key().decode("utf-8").strip().split()
        return f"{parts[0]} {parts[1]}" if len(parts) >= 2 else None
    except Exception:  # noqa: BLE001 — an unreadable key is "no key", not a crash
        logger.warning("Could not read the server host key", exc_info=True)
        return None


def _ensure_known_hosts_file(path: str) -> bool:
    """Create the known_hosts file (and parents) if missing. Returns writable."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            open(path, "a", encoding="utf-8").close()
        return os.access(path, os.W_OK)
    except OSError as exc:
        logger.warning("known_hosts path %r is not usable (%s)", path, exc)
        return False


def _host_is_pinned(path: str, host: str) -> bool:
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Format: "host[,host2] keytype base64..."
                hosts_field = line.split(None, 1)[0]
                if host in hosts_field.split(","):
                    return True
    except OSError:
        return False
    return False


def _pin_host_key(conn: asyncssh.SSHClientConnection, path: str, host: str) -> None:
    """Append the connection's server host key to *path* for *host*."""
    try:
        host_key = conn.get_server_host_key()
        if host_key is None:
            logger.warning("TOFU: no server host key available to pin for %s", host)
            return
        pub = host_key.export_public_key().decode("utf-8").strip()
        # export_public_key() -> "keytype base64 [comment]"; prefix with host.
        parts = pub.split()
        line = f"{host} {parts[0]} {parts[1]}\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
        logger.info("TOFU: pinned host key for %s into %s", host, path)
    except Exception as exc:  # noqa: BLE001 - pinning is best-effort
        logger.warning("TOFU: failed to pin host key for %s: %s", host, exc)


async def connect_with_policy(
    connect_kwargs: dict, *, timeout: float | None = None
) -> asyncssh.SSHClientConnection:
    """Open an asyncssh connection honouring the configured host-key policy.

    *connect_kwargs* must NOT contain ``known_hosts`` — this function sets it.
    """
    policy = _policy()
    host = str(connect_kwargs.get("host", "")).strip()
    # Once per process, and only where the promise cannot be kept (AUD-0819-06).
    warn_if_known_hosts_ephemeral()

    async def _connect(kwargs: dict) -> asyncssh.SSHClientConnection:
        coro = asyncssh.connect(**kwargs)
        if timeout is not None:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

    if policy == "disabled":
        # F-SEC-4: this is an explicit, logged, non-production-only override.
        logger.warning(
            "SSH host-key verification is DISABLED (ssh_host_key_policy=disabled) "
            "for connection to %s — vulnerable to man-in-the-middle. "
            "Set SSH_HOST_KEY_POLICY=tofu or strict in production.",
            host,
        )
        connect_kwargs["known_hosts"] = None
        return await _connect(connect_kwargs)

    path = settings.ssh_known_hosts_path
    writable = _ensure_known_hosts_file(path)

    if policy == "strict":
        connect_kwargs["known_hosts"] = path
        return await _connect(connect_kwargs)

    if policy == "tofu":
        if not writable:
            # F-SSH-01. This used to set `known_hosts = None` and connect anyway — for
            # this connection and every later one — which turns the policy off and logs
            # about it. The pin moves into process memory instead: the first connect to a
            # host is unverified, which is what trust-on-first-use is, and every later
            # connect is checked against the key that first one presented. Where the file
            # is writable but the disk does not survive a restart (AUD-0819-06) that is
            # already the guarantee, so nothing is downgraded by it.
            return await _connect_with_memory_pin(_connect, connect_kwargs, host, path)

        if _host_is_pinned(path, host):
            # Already trusted — verify against the pinned key.
            connect_kwargs["known_hosts"] = path
            return await _connect(connect_kwargs)

        # First use: connect unverified, then pin for next time.
        connect_kwargs["known_hosts"] = None
        conn = await _connect(connect_kwargs)
        _pin_host_key(conn, path, host)
        return conn

    # F-SEC-4: fail closed — an unrecognised policy must never silently
    # disable verification.
    logger.warning(
        "Unknown ssh_host_key_policy %r; treating as 'strict' (fail closed)",
        policy,
    )
    connect_kwargs["known_hosts"] = path
    return await _connect(connect_kwargs)


async def _connect_with_memory_pin(
    connect: Callable[[dict], Awaitable[asyncssh.SSHClientConnection]],
    connect_kwargs: dict,
    host: str,
    path: str,
) -> asyncssh.SSHClientConnection:
    """Trust-on-first-use with the pin held in memory, because the file refused it.

    Verification happens *after* the handshake rather than inside asyncssh, so the first
    connection is genuinely unverified — that is TOFU's premise, not a shortcut. What
    changes is the second one: a host whose key no longer matches is disconnected and
    raised on, where before it was accepted without comment.
    """
    connect_kwargs["known_hosts"] = None
    conn = await connect(connect_kwargs)

    blob = _host_key_blob(conn)
    if blob is None:
        # Nothing to compare a later connection against. Recording the host would
        # assert a check that cannot happen.
        logger.warning(
            "ssh_host_key_policy=tofu but %r is not writable and %s presented no "
            "readable host key: this connection is unverified and cannot be pinned",
            path,
            host,
        )
        return conn

    pinned = _MEMORY_PINS.get(host)
    if pinned is None:
        _MEMORY_PINS[host] = blob
        logger.warning(
            "ssh_host_key_policy=tofu but %r is not writable; pinned %s in memory for "
            "this process only. The pin is lost on restart, so the first connection "
            "after every restart is unverified. Point SSH_KNOWN_HOSTS_PATH at durable "
            "storage to fix that properly.",
            path,
            host,
        )
        return conn

    if pinned != blob:
        conn.abort()
        raise HostKeyChangedError(
            f"Host key for {host} changed since this process first connected to it. "
            "Either the server was rebuilt or the connection is being intercepted; "
            "restart the app to accept a legitimate new key."
        )
    return conn
