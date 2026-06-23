"""Safe-transport validation for user-supplied git repository URLs.

`git` honors remote-helper transports such as ``ext::`` and ``fd::`` which
execute arbitrary commands, and treats leading-dash values as options. A
user-controlled ``repo_url`` flowing into ``git ls-remote`` / ``git clone``
is therefore an RCE vector unless the transport is constrained. This module
provides an allowlist guard (used at the API boundary and again in the
``RepoAnalyzer`` as defense-in-depth) plus the ``GIT_ALLOW_PROTOCOL`` value
to pin into the git subprocess environment.
"""

import re

# Protocols git is permitted to use; intentionally excludes ``ext``, ``fd``,
# ``file`` and the insecure ``git://`` daemon protocol.
GIT_ALLOWED_PROTOCOLS = "http:https:ssh"

_ALLOWED_SCHEMES = ("https://", "http://", "ssh://")
# scp-like syntax: user@host:path (always SSH transport, never with a scheme).
_SCP_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*@[A-Za-z0-9_.-]+:[^\s]+$")


def validate_repo_url(repo_url: str) -> str:
    """Return the trimmed URL if it uses a safe git transport, else raise.

    Accepts ``https://``, ``http://``, ``ssh://`` URLs and ``user@host:path``
    scp syntax. Rejects everything else — including ``ext::``/``fd::`` remote
    helpers, ``file://`` paths, the ``git://`` daemon protocol, and values
    beginning with ``-`` (git option injection).
    """
    if not isinstance(repo_url, str):
        raise ValueError("Repository URL must be a string")
    url = repo_url.strip()
    if not url:
        raise ValueError("Repository URL is required")
    if url.startswith("-"):
        raise ValueError("Repository URL must not start with '-'")
    if url.lower().startswith(_ALLOWED_SCHEMES):
        return url
    if "://" not in url and _SCP_RE.match(url):
        return url
    raise ValueError("Repository URL must use https://, http://, ssh://, or git@host:path")
