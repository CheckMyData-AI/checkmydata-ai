"""What "the connection failed, try again" looks like in each driver (C-05).

The service-level retry caught ``(TimeoutError, ConnectionError, OSError)``. PyMySQL —
the driver this deployment's MySQL connections use — raises
``pymysql.err.OperationalError`` for a refused socket, a lost connection and a handshake
timeout, and it is none of those three, so the one engine most likely to be reached
through a bastion was never retried at all, while the engines that were retried
multiplied an already-retrying tunnel.

Each driver is imported defensively — the optional ones are not installed in every image
— and only `ImportError` is caught: a driver that is present but broken is a defect, and
hiding it here would turn it into "this database is simply never retried".
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _driver_errors() -> tuple[type[Exception], ...]:
    found: list[type[Exception]] = []

    try:
        import pymysql.err

        found += [pymysql.err.OperationalError, pymysql.err.InterfaceError]
    except ImportError:  # pragma: no cover - driver absent in a trimmed image
        logger.debug("pymysql not installed; its transient errors are not retried")

    try:
        import asyncpg.exceptions

        found += [
            asyncpg.exceptions.ConnectionDoesNotExistError,
            asyncpg.exceptions.ConnectionFailureError,
            asyncpg.exceptions.TooManyConnectionsError,
        ]
    except ImportError:  # pragma: no cover
        logger.debug("asyncpg not installed; its transient errors are not retried")

    try:
        import clickhouse_connect.driver.exceptions as ch

        found.append(ch.OperationalError)
    except ImportError:  # pragma: no cover
        logger.debug("clickhouse_connect not installed; its transient errors are not retried")

    try:
        import pymongo.errors

        found += [pymongo.errors.AutoReconnect, pymongo.errors.NetworkTimeout]
    except ImportError:  # pragma: no cover
        logger.debug("pymongo not installed; its transient errors are not retried")

    return tuple(found)


#: Retry only on these. Built once at import — the driver set does not change at runtime.
TRANSIENT_CONNECT_ERRORS: tuple[type[Exception], ...] = (
    TimeoutError,
    ConnectionError,
    OSError,
) + _driver_errors()


#: MySQL server error codes that are an ANSWER, not a fault (T05b, audit 2026-09-23 F-C3).
#: PyMySQL raises every one of them as ``OperationalError`` — the same class as a refused
#: socket — so a class check alone retried a wrong password and, through a tunnel, tore
#: the shared tunnel down to "fix" it. 1044/1045 access denied, 1049 unknown database,
#: 1130 host not allowed, 1251 auth plugin unsupported, 1698 access denied (auth_socket).
_MYSQL_REFUSALS = frozenset({1044, 1045, 1049, 1130, 1251, 1698})


def is_transient_connect_error(exc: BaseException) -> bool:
    """Is *exc* a connect failure worth trying again — the network, not the server's word?

    The predicate the retry and the tunnel rebuild ask (see ``docs/audits/
    2026-09-23-recent-work-audit.md`` §3.2). ``TRANSIENT_CONNECT_ERRORS`` stays the coarse
    net for ``except`` clauses; this narrows it where one driver class carries both.
    """
    if not isinstance(exc, TRANSIENT_CONNECT_ERRORS):
        return False
    if _PYMYSQL_ERRORS and isinstance(exc, _PYMYSQL_ERRORS):
        code = exc.args[0] if exc.args else None
        return code not in _MYSQL_REFUSALS
    return True


def _pymysql_errors() -> tuple[type[Exception], ...]:
    try:
        import pymysql.err
    except ImportError:  # pragma: no cover - driver absent in a trimmed image
        logger.debug("pymysql not installed; no MySQL refusal codes to separate")
        return ()
    return (pymysql.err.OperationalError, pymysql.err.InterfaceError)


_PYMYSQL_ERRORS: tuple[type[Exception], ...] = _pymysql_errors()
