"""Safe-transport validation for user-supplied git repository URLs.

`git` honors remote-helper transports such as ``ext::`` and ``fd::`` which
execute arbitrary commands, and treats leading-dash values as options. A
user-controlled ``repo_url`` flowing into ``git ls-remote`` / ``git clone``
is therefore an RCE vector unless the transport is constrained. This module
provides an allowlist guard (used at the API boundary and again in the
``RepoAnalyzer`` as defense-in-depth) plus the ``GIT_ALLOW_PROTOCOL`` value
to pin into the git subprocess environment.

It also guards against SSRF (FA-004): the URL host is DNS-resolved and
loopback/private/link-local/reserved targets are rejected, so an
authenticated user cannot turn ``git ls-remote`` into an internal network
probe or reach cloud metadata endpoints (169.254.169.254). Self-hosted
deployments with an internal git server can opt out via the
``REPO_ALLOW_PRIVATE_HOSTS`` setting.
"""

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from app.config import settings

# Protocols git is permitted to use; intentionally excludes ``ext``, ``fd``,
# ``file`` and the insecure ``git://`` daemon protocol.
GIT_ALLOWED_PROTOCOLS = "http:https:ssh"

_ALLOWED_SCHEMES = ("https://", "http://", "ssh://")
# scp-like syntax: user@host:path (always SSH transport, never with a scheme).
_SCP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*@[A-Za-z0-9_.-]+:[^\s]+$")

# Git branch/ref names: letters, digits, '.', '_', '-', '/'; must start with an
# alphanumeric or '.'/'_' (never '-', which git would parse as an option).
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._/-]*$")


def validate_git_ref(ref: str) -> str:
    """Return the trimmed branch/ref if it is a safe git ref name, else raise.

    GitPython passes the branch as an argument (no shell), so this guards against
    option injection (leading ``-``, ``--upload-pack=…``) and malformed refs rather
    than shell escapes. Rejects empty, leading-dash, ``..`` range syntax, trailing
    ``/``, the reserved ``.lock`` suffix, and anything outside the ref charset.
    """
    if not isinstance(ref, str):
        raise ValueError("Branch/ref must be a string")
    r = ref.strip()
    if not r:
        raise ValueError("Branch/ref is required")
    if r.startswith("-") or ".." in r or r.endswith("/") or r.endswith(".lock"):
        raise ValueError("Invalid branch/ref name")
    if not _GIT_REF_RE.match(r):
        raise ValueError("Branch/ref may contain only letters, digits, '.', '_', '-', '/'")
    return r


def _extract_host(url: str) -> str:
    """Return the hostname of a transport-validated URL (scheme or scp-like)."""
    if "://" in url:
        try:
            host = urlsplit(url).hostname
        except ValueError as exc:  # malformed authority, e.g. bad IPv6 literal
            raise ValueError("Repository URL has an invalid host") from exc
    else:
        # scp-like user@host:path (shape already enforced by _SCP_RE).
        host = url.rsplit("@", 1)[-1].split(":", 1)[0]
    host = (host or "").strip().lower()
    if not host:
        raise ValueError("Repository URL has no host")
    return host


def _resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """DNS-resolve *host*, raising ValueError when it cannot be resolved.

    Fail closed (FA-004): an unresolvable host is rejected rather than waved
    through, so a DNS-error difference can't smuggle internal targets past
    the guard.
    """
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError) as exc:  # gaierror is an OSError subclass
        raise ValueError(f"Repository host {host!r} could not be resolved") from exc
    ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        try:
            ips.add(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    if not ips:
        raise ValueError(f"Repository host {host!r} could not be resolved")
    return ips


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for globally routable unicast addresses."""
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _reject_internal_host(url: str, *, allow_private_hosts: bool) -> None:
    """FA-004 SSRF guard: reject loopback/private/link-local/reserved repo hosts.

    Every resolved address must be public — a host that resolves to a mix of
    public and private IPs is rejected (fail closed). The whole check is
    skipped only when the deployment explicitly opts into private git hosts.
    """
    if allow_private_hosts:
        return
    host = _extract_host(url)
    for ip in _resolve_host_ips(host):
        if not _is_public_ip(ip):
            raise ValueError(
                f"Repository host {host!r} resolves to a non-public address ({ip}); "
                "set REPO_ALLOW_PRIVATE_HOSTS=true only for trusted internal git servers"
            )


def validate_repo_url(repo_url: str, *, allow_private_hosts: bool | None = None) -> str:
    """Return the trimmed URL if it uses a safe git transport, else raise.

    Accepts ``https://``, ``http://``, ``ssh://`` URLs and ``user@host:path``
    scp syntax. Rejects everything else — including ``ext::``/``fd::`` remote
    helpers, ``file://`` paths, the ``git://`` daemon protocol, and values
    beginning with ``-`` (git option injection).

    SSRF guard (FA-004): the host is DNS-resolved and rejected when any
    resolved address is loopback/private/link-local/multicast/reserved, or
    when it cannot be resolved at all. ``allow_private_hosts`` overrides the
    guard for one call; when None, the ``repo_allow_private_hosts`` setting
    decides.
    """
    if not isinstance(repo_url, str):
        raise ValueError("Repository URL must be a string")
    url = repo_url.strip()
    if not url:
        raise ValueError("Repository URL is required")
    if url.startswith("-"):
        raise ValueError("Repository URL must not start with '-'")
    if url.lower().startswith(_ALLOWED_SCHEMES) or ("://" not in url and _SCP_RE.match(url)):
        if allow_private_hosts is None:
            allow_private_hosts = settings.repo_allow_private_hosts
        _reject_internal_host(url, allow_private_hosts=allow_private_hosts)
        return url
    raise ValueError("Repository URL must use https://, http://, ssh://, or git@host:path")
