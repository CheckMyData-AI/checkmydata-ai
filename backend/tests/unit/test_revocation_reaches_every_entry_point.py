"""Revoking a session must revoke it everywhere (board row 1.12).

A JWT carries the user's `token_version` at mint time. Bumping the column — a
password change, "sign out everywhere" (`auth.py:334`) — is what invalidates every
token minted before it. `app/api/deps.py:78` compares them and refuses on a
mismatch, with a comment explaining exactly that.

`app/mcp_server/auth.py`'s `resolve_user_from_jwt` decoded the token, loaded the
user, checked `is_active` — and **never compared the versions**. So revoking a
user's sessions killed their HTTP access and left their MCP access alive until the
token expired on its own. A stolen or deliberately-revoked JWT kept working
against `/mcp`.

Third occurrence in this programme of one shape: a check written once per entry
point, absent at one of them. #267 was the same (project scope, three chat
endpoints), and so was `TraceMeta` (routing, twelve call sites). The fix is the
same too — **one function both paths call**, not a copied `if`, because the copy
is what goes missing at the fourth entry point.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.core.identity import RevokedTokenError, assert_token_not_revoked


class _User:
    def __init__(self, token_version: int = 0, is_active: bool = True) -> None:
        self.id = "u1"
        self.email = "u@example.com"
        self.token_version = token_version
        self.is_active = is_active


class TestTheSharedCheck:
    def test_a_matching_version_passes(self):
        assert_token_not_revoked({"sub": "u1", "ver": 3}, _User(token_version=3))

    def test_a_stale_version_is_refused(self):
        """The whole point: a token minted before the bump must stop working."""
        with pytest.raises(RevokedTokenError):
            assert_token_not_revoked({"sub": "u1", "ver": 2}, _User(token_version=3))

    def test_a_missing_claim_defaults_to_zero_and_does_not_force_a_logout(self):
        """Tokens minted before the claim existed carry no `ver`. Treating that as
        a mismatch would sign out every such user at deploy time — the HTTP path
        made the same choice and says so in its own comment."""
        assert_token_not_revoked({"sub": "u1"}, _User(token_version=0))

    def test_a_missing_claim_against_a_bumped_user_is_still_refused(self):
        """The default is a grace for old tokens, not a bypass: once the user has
        revoked anything, a claimless token is a pre-revocation token."""
        with pytest.raises(RevokedTokenError):
            assert_token_not_revoked({"sub": "u1"}, _User(token_version=1))

    def test_a_null_token_version_is_treated_as_zero(self):
        """The column is non-null in the model, but a row written before the
        migration — or a stubbed user — can present ``None``. Comparing ``0 !=
        None`` would refuse a valid token."""
        user = _User()
        user.token_version = None  # type: ignore[assignment]
        assert_token_not_revoked({"sub": "u1", "ver": 0}, user)


class TestBothEntryPointsUseIt:
    """The copied `if` is what goes missing. One function, two callers."""

    @pytest.mark.parametrize(
        "path",
        ["app/api/deps.py", "app/mcp_server/auth.py"],
    )
    def test_the_entry_point_delegates_to_the_shared_check(self, path):
        src = Path(path).read_text(encoding="utf-8")
        assert "assert_token_not_revoked" in src, (
            f"{path} must ask the shared check rather than comparing versions itself"
        )

    @pytest.mark.parametrize(
        "path",
        ["app/api/deps.py", "app/mcp_server/auth.py"],
    )
    def test_no_entry_point_compares_the_versions_inline(self, path):
        """An inline comparison beside the shared call is how the two drift."""
        src = Path(path).read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in src.splitlines()
            if "token_version" in line
            and "!=" in line
            and not line.strip().startswith("#")
            and "assert_token_not_revoked" not in line
        ]
        assert not offenders, f"{path} still compares versions inline: {offenders}"

    def test_the_shared_check_lives_where_both_can_reach_it(self):
        """`app/api/deps.py` is FastAPI-bound and `app/mcp_server/auth.py` is not;
        neither may import the other. A leaf module is the only home that does not
        invert a dependency — the same reason `app/core/failure_kind.py` exists."""
        import ast

        src = Path(inspect.getfile(assert_token_not_revoked)).read_text(encoding="utf-8")
        app_imports = {
            node.module
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app")
        }
        assert not app_imports, (
            f"the shared check must import nothing from app; found {app_imports}"
        )


class TestTheMcpPathActuallyRefuses:
    """The behaviour, not the wiring: a revoked token must not resolve."""

    async def test_a_revoked_jwt_does_not_resolve_to_a_principal(self, monkeypatch):
        from app.mcp_server import auth as mcp_auth

        monkeypatch.setattr(
            mcp_auth._auth_svc, "decode_token", lambda _t: {"sub": "u1", "ver": 1}, raising=False
        )

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        monkeypatch.setattr(mcp_auth, "async_session_factory", lambda: _Session())

        async def _get_by_id(_session, _uid):
            return _User(token_version=5)  # revoked since this token was minted

        monkeypatch.setattr(mcp_auth._auth_svc, "get_by_id", _get_by_id, raising=False)

        with pytest.raises(mcp_auth.MCPAuthError):
            await mcp_auth.resolve_user_from_jwt("stale.jwt.token")

    async def test_a_current_jwt_still_resolves(self, monkeypatch):
        """The control. A guard that refuses everything is not a guard."""
        from app.mcp_server import auth as mcp_auth

        monkeypatch.setattr(
            mcp_auth._auth_svc, "decode_token", lambda _t: {"sub": "u1", "ver": 5}, raising=False
        )

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        monkeypatch.setattr(mcp_auth, "async_session_factory", lambda: _Session())

        async def _get_by_id(_session, _uid):
            return _User(token_version=5)

        monkeypatch.setattr(mcp_auth._auth_svc, "get_by_id", _get_by_id, raising=False)

        principal = await mcp_auth.resolve_user_from_jwt("fresh.jwt.token")
        assert principal["user_id"] == "u1"


class TestItFailsClosedOnAnUnreadableVersion:
    """Found by breaking a pre-existing test, not by design.

    `test_mcp_server.py::test_jwt_valid` stubs the user with a bare `MagicMock`,
    so `token_version` was a Mock — unreadable — and the new check refused. The
    fixture was incomplete rather than the behaviour wrong: it asserted "a valid
    JWT resolves" and never modelled a field nothing used to read.

    But it exposed a real fragility in the first implementation. A bare `!=`
    against an unreadable value refuses, which is right; against a value that is
    merely the WRONG TYPE — a column arriving as `"3"` — it would have refused
    every token forever, because `0 != "3"` and `3 != "3"` are both true.
    """

    def test_a_string_version_is_coerced_rather_than_locking_everyone_out(self):
        user = _User()
        user.token_version = "3"  # type: ignore[assignment]
        assert_token_not_revoked({"sub": "u1", "ver": 3}, user)

    def test_an_unreadable_version_is_refused(self):
        user = _User()
        user.token_version = object()  # type: ignore[assignment]
        with pytest.raises(RevokedTokenError, match="could not be established"):
            assert_token_not_revoked({"sub": "u1", "ver": 0}, user)

    def test_a_boolean_is_unreadable_and_not_an_int(self):
        """`bool` subclasses `int`, so `True == 1` would silently pass a flag off
        as a version."""
        user = _User()
        user.token_version = True  # type: ignore[assignment]
        with pytest.raises(RevokedTokenError):
            assert_token_not_revoked({"sub": "u1", "ver": 1}, user)

    def test_zero_is_a_real_version_and_not_absence(self):
        """A user who has never revoked anything is at 0, which must pass."""
        assert_token_not_revoked({"sub": "u1", "ver": 0}, _User(token_version=0))
