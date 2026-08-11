"""F-MCP-04 — why the MCP Host allow-list is NOT derived, and what it must contain.

`MCP_ENABLED=true` and `MCP_MOUNT_ENABLED=true` in production with `MCP_ALLOWED_HOSTS`
empty means DNS-rebinding protection is off on a publicly reachable endpoint
(`POST /mcp/mcp` returns 200 in the production logs). The server has warned about it at
every boot for weeks, which is what a warning without a control is worth.

The obvious fix — derive the list from `cors_origins` — was implemented, tested green,
and then **reverted before shipping**, because production's actual `CORS_ORIGINS` are
`https://checkmydata.ai` and the web dyno's `herokuapp.com` domain. Neither is
`api.checkmydata.ai`, the host MCP clients actually address. Deriving would have turned
protection ON with a list excluding the real host and rejected every legitimate MCP
call: a guess that breaks the endpoint is worse than a documented gap.

CORS origins answer "which browser pages may call us". A Host allow-list answers "what
name are we served under". Those are different questions, and this deployment is the
case where they differ.

What remains is an operator action — `MCP_ALLOWED_HOSTS=api.checkmydata.ai` — and these
tests pin the contract it has to satisfy.
"""

from __future__ import annotations

from app.config import Settings


def _s(**kw) -> Settings:
    base = dict(jwt_secret="x" * 40, environment="development")
    base.update(kw)
    return Settings(**base)


def test_the_allow_list_is_taken_verbatim_and_never_guessed():
    """No derivation, no surprises — whatever the operator sets is what is enforced."""
    s = _s(
        mcp_enabled=True,
        mcp_mount_enabled=True,
        mcp_allowed_hosts=["api.checkmydata.ai"],
        cors_origins=["https://checkmydata.ai"],
    )
    assert s.mcp_allowed_hosts == ["api.checkmydata.ai"]


def test_cors_origins_do_not_leak_into_the_allow_list():
    """The regression this file exists for: they answer different questions."""
    s = _s(
        mcp_enabled=True,
        mcp_mount_enabled=True,
        mcp_allowed_hosts=[],
        cors_origins=["https://checkmydata.ai", "https://x.herokuapp.com"],
    )
    assert s.mcp_allowed_hosts == [], (
        "deriving from CORS origins would enable protection with a list that excludes "
        "the API host and break every MCP call"
    )


def test_protection_is_on_exactly_when_the_list_is_non_empty():
    """`enable_dns_rebinding_protection=bool(mcp_allowed_hosts)` in server.py."""
    assert bool(_s(mcp_allowed_hosts=[]).mcp_allowed_hosts) is False
    assert bool(_s(mcp_allowed_hosts=["api.checkmydata.ai"]).mcp_allowed_hosts) is True
