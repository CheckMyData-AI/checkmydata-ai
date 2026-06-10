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

import asyncssh

from app.config import settings

logger = logging.getLogger(__name__)


def _policy() -> str:
    # F-SEC-4: fail towards verification — an unset/blank policy means "tofu".
    return (settings.ssh_host_key_policy or "tofu").strip().lower()


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
            logger.warning(
                "ssh_host_key_policy=tofu but %r is not writable; "
                "falling back to no verification for this connection",
                path,
            )
            connect_kwargs["known_hosts"] = None
            return await _connect(connect_kwargs)

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
