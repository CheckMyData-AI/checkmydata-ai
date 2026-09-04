"""Whether a decoded token is still the one its user is willing to honour.

A JWT carries the user's ``token_version`` at mint time. Bumping that column —
a password change, or "sign out everywhere" (:mod:`app.api.routes.auth`) — is the
whole revocation mechanism: it invalidates every token minted before it without
needing a denylist.

The comparison lived inline in :mod:`app.api.deps` and **nowhere else**, so the
MCP server's JWT path decoded a token, loaded the user, checked ``is_active`` and
resolved a principal from a token the user had already revoked. Revoking sessions
killed HTTP access and left ``/mcp`` open until the token expired on its own.

Third time in this programme that one shape has produced a defect: a check
written once per entry point and absent at one of them. #267 was the project
scope across three chat endpoints; :class:`~app.core.trace_meta.TraceMeta` was the
routing across twelve call sites. Each was fixed the same way — **one function
every caller asks** — because the copy is what goes missing at the next entry
point, and a reviewer cannot see an absence.

Standard library only, and a test enforces it: :mod:`app.api.deps` is FastAPI-bound
and :mod:`app.mcp_server.auth` is not, neither may import the other, so a leaf
module is the only home that does not invert a dependency.
"""

from __future__ import annotations

from typing import Any, Protocol


class _HasTokenVersion(Protocol):
    """The one field this check reads off a user row."""

    token_version: int


class RevokedTokenError(Exception):
    """The token was minted before the user's current ``token_version``."""


def assert_token_not_revoked(payload: dict[str, Any], user: _HasTokenVersion) -> None:
    """Raise :class:`RevokedTokenError` when *payload* predates the user's revocation.

    ``ver`` defaults to 0 for tokens minted before the claim existed, and
    ``token_version`` to 0 for a row written before the column did. That default
    is a **grace for old tokens, not a bypass**: a claimless token against a user
    who has revoked anything is by definition a pre-revocation token, and the
    comparison refuses it.

    Raises rather than returning a bool so a caller cannot ignore the answer by
    forgetting an ``if`` — the failure mode this module was created to remove.
    """
    minted_at = _as_version(payload.get("ver"))
    current = _as_version(getattr(user, "token_version", None))
    if minted_at is None or current is None:
        # Fail closed. If the user's current version cannot be established, then
        # neither can "this token is current" — and a revocation check that
        # guesses is not one. Coercion rather than a bare compare, because a
        # column arriving as `"3"` from some driver would otherwise refuse every
        # token forever: `0 != "3"` and `3 != "3"` are both true.
        raise RevokedTokenError(
            f"token version could not be established (token={payload.get('ver')!r}, "
            f"user={getattr(user, 'token_version', None)!r})"
        )
    if minted_at != current:
        raise RevokedTokenError(
            f"token was minted at version {minted_at}; the user is at {current}"
        )


def _as_version(value: object) -> int | None:
    """Coerce a version to ``int``. ``None``/absent is 0; anything else is None.

    ``None`` means *unreadable*, which the caller turns into a refusal — the
    distinction matters, because 0 is a legitimate version (a user who has never
    revoked anything) and must not be confused with "no idea".
    """
    if value is None:
        return 0
    if isinstance(value, bool):  # bool is an int; a flag here is a programming error
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None
