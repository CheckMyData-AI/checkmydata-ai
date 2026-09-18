"""One reading of a connection string, shared by the engines that accept one (C-06).

Two boxes disagreed about the same string. `urlparse` leaves the userinfo
**percent-encoded** — `p%40ss` stays `p%40ss` — while the connection form decodes it
(`frontend/src/lib/connection-string.ts`), so a password containing `@`, `/` or `:`
worked in the browser's preview and failed at the server with an authentication error
that named nothing. And a DSN with no user defaulted to `root` on MySQL, which is a
different account from the one the string described: an authentication failure is a
better answer than a successful login as somebody else.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote, urlparse


class DsnError(ValueError):
    """The connection string cannot be read as one."""


@dataclass(frozen=True)
class ParsedDsn:
    host: str
    port: int | None
    database: str
    user: str
    password: str


def parse_dsn(connection_string: str, *, default_port: int | None = None) -> ParsedDsn:
    """Read a DSN the way the form that produced it does.

    Raises :class:`DsnError` when it carries no user: every engine here authenticates,
    and guessing the account is how a string that describes one login becomes another.
    """
    parsed = urlparse(connection_string)
    if not parsed.hostname:
        raise DsnError("The connection string names no host")
    user = unquote(parsed.username or "")
    if not user:
        raise DsnError(
            "The connection string names no user. Add one (user:password@host/db) rather "
            "than relying on a default account — a login as somebody else is worse than a "
            "refusal."
        )
    return ParsedDsn(
        host=parsed.hostname,
        port=parsed.port or default_port,
        database=unquote((parsed.path or "").lstrip("/").split("/")[0]),
        user=user,
        password=unquote(parsed.password or ""),
    )
