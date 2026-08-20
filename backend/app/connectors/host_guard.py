"""Where a connection is allowed to point (F-CONN-04).

`db_host`, `ssh_host` and a DSN's host are user-supplied and reach a socket, so an
authenticated user can aim them anywhere the server can reach — the cloud metadata
endpoint, the app's own Redis, a service on the internal network — and read the
connection-test error text as an oracle for what answered.

**The obvious guard is the wrong one here.** `validate_repo_url` rejects every non-public
address by default, and that is right for a git remote: a public git host is the normal
case. A database is the opposite. Most deployments reach theirs at `10.x`, `192.168.x` or
`127.0.0.1`, so refusing private addresses by default would break the product for the
majority in order to protect the minority who run it multi-tenant. A guard that breaks
the normal case gets turned off, and then it protects nobody.

So the default is narrow and absolute, and the broad rule is opt-in:

* **Always refused: the cloud metadata endpoints.** No database has ever lived at
  `169.254.169.254`, and what does live there hands out credentials for the whole cloud
  account. Refusing it costs no deployment anything.
* **Optionally refused: every private/loopback/link-local address**
  (`connection_allow_private_hosts=False`), for operators running this multi-tenant,
  where a tenant reaching `127.0.0.1` reaches *your* infrastructure.

Both resolve DNS and check **every** address returned, because `db.attacker.test` may
resolve to a public address in the operator's check and a private one a second later, and
because a name can carry several records.
"""

import ipaddress
import logging
import socket

from app.config import settings

logger = logging.getLogger(__name__)


class HostNotAllowedError(ValueError):
    """A connection host points somewhere connections may not point."""


#: Link-local ranges reserved for instance metadata. `169.254.169.254` is AWS, GCP, Azure,
#: DigitalOcean and Oracle; `fd00:ec2::254` is EC2's IPv6 form. These are refused on every
#: deployment, private-host setting or not — there is no database behind them, and what is
#: behind them issues credentials for the account the app runs in.
_METADATA_IPS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "169.254.170.2",  # ECS task metadata / credential endpoint
        "fd00:ec2::254",
    }
)

#: Names that resolve to the above, refused before DNS so a split-horizon resolver cannot
#: answer differently for us than it does for the check.
_METADATA_NAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)


class _UnresolvableError(Exception):
    """DNS gave nothing back. Whether that refuses the host depends on the mode."""


def _resolve(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Every address *host* resolves to, or :class:`_UnresolvableError`.

    What the caller does with that differs by mode, and the difference is the whole
    reason this raises its own type instead of deciding here — see
    :func:`check_connection_host`.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:
        raise _UnresolvableError(str(exc)) from exc
    ips = set()
    for info in infos:
        try:
            ips.add(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not ips:
        raise _UnresolvableError("no addresses returned")
    return ips


def _is_internal(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_connection_host(host: str | None, *, field: str = "db_host") -> None:
    """Raise :class:`HostNotAllowedError` when *host* may not be connected to.

    A blank host is not this function's business — an MCP or analytics connection has
    none, and "is a host required here" is answered by the model validators.
    """
    candidate = (host or "").strip().rstrip(".").lower()
    if not candidate:
        return

    if candidate in _METADATA_NAMES:
        raise HostNotAllowedError(
            f"{field} {host!r} is a cloud metadata endpoint, which serves credentials "
            "rather than data."
        )

    # A literal address needs no DNS, and resolving one would be a needless round trip.
    try:
        literal = ipaddress.ip_address(candidate.strip("[]"))
    except ValueError:
        literal = None

    if literal is not None:
        addresses = {literal}
    else:
        try:
            addresses = _resolve(candidate)
        except _UnresolvableError as exc:
            # A database hostname that this process cannot resolve *right now* is
            # ordinary: the user configures the connection before the VPN is up, or the
            # name resolves only from inside the network, or only through the SSH
            # tunnel's far side. The connection test is where reachability is decided.
            # Refusing here would make the guard an outage at configuration time —
            # measured: `test_database_connection_still_creates_with_its_defaults` went
            # 422 on `db.internal` the moment this was fail-closed.
            #
            # In strict mode the calculus flips: the operator asked for public addresses
            # only, and "I could not check" is not "public". Failing open there would let
            # a caller choose whether the guard runs by choosing a name that does not
            # resolve on the first lookup.
            if not settings.connection_allow_private_hosts:
                raise HostNotAllowedError(
                    f"{field} {host!r} could not be resolved ({exc}), and this deployment "
                    "accepts only public hosts, so it cannot be verified."
                ) from exc
            logger.info(
                "Could not resolve %s %r (%s); it is accepted unverified. The connection "
                "test is what decides whether it is reachable.",
                field,
                host,
                exc,
            )
            return

    for ip in addresses:
        if str(ip) in _METADATA_IPS:
            raise HostNotAllowedError(
                f"{field} {host!r} resolves to the cloud metadata endpoint ({ip}), "
                "which serves credentials rather than data."
            )
        if not settings.connection_allow_private_hosts and _is_internal(ip):
            raise HostNotAllowedError(
                f"{field} {host!r} resolves to a non-public address ({ip}). Set "
                "CONNECTION_ALLOW_PRIVATE_HOSTS=true if this deployment's databases "
                "live on an internal network."
            )


def _dsn_host(connection_string: str | None) -> str | None:
    """The host inside a DSN, when one can be read out of it.

    Deliberately best-effort: every engine spells its DSN differently and parsing all of
    them here would be a second, worse copy of their drivers. What this catches is the
    common `scheme://user:pass@host:port/db` shape, which is what a user pastes. A DSN
    this cannot parse is left to the driver — the guard's job is to remove the easy path,
    not to claim a completeness it does not have.
    """
    if not connection_string or "://" not in connection_string:
        return None
    from urllib.parse import urlsplit

    try:
        return urlsplit(connection_string.strip()).hostname
    except ValueError:
        return None


async def check_connection_targets(
    *,
    db_host: str | None = None,
    ssh_host: str | None = None,
    connection_string: str | None = None,
) -> None:
    """Check every host a connection would reach, off the event loop.

    `getaddrinfo` blocks, and this runs on the request path, so it goes to a thread. The
    repo-URL guard makes the same call synchronously inside a Pydantic validator; that is
    a pre-existing trade-off rather than a precedent worth copying into a new one.
    """
    import asyncio

    for value, field in (
        (db_host, "db_host"),
        (ssh_host, "ssh_host"),
        (_dsn_host(connection_string), "connection_string host"),
    ):
        if value:
            await asyncio.to_thread(check_connection_host, value, field=field)
