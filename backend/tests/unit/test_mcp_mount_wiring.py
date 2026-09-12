"""The HTTP MCP mount is decided by two flags, and asking must cost nothing.

This file used to `importlib.reload(app.main)` inside a settings patch, which is
TEST-13: reload rebinds `app.main.app` to a **new** FastAPI instance while the six
modules that did `from app.main import app` during collection keep the original, and
`tests/integration/conftest.py` imports it lazily — so `dependency_overrides[get_db]`
could be installed on a different object than the one a test was driving. `make check`
runs unit and integration in one process; CI runs two. The two checks were not the same
check, and the one a contributor runs locally was the fragile one.

Worse, the restore reload sat *after* the assertion, so a failure left the module
permanently swapped for every later test in the session — a single red test could turn
an unrelated suite red and give no hint why.

The condition is a function now, so the question is answerable without rebuilding
anything.
"""

from unittest.mock import patch

import pytest

import app.main as main_mod


def _routes_contain_mcp(app) -> bool:
    return any(getattr(r, "path", "").startswith("/mcp") for r in app.routes)


@pytest.mark.parametrize(
    ("mcp_enabled", "mount_enabled", "expected"),
    [
        (False, False, False),
        (True, False, False),
        # `mcp_mount_enabled` alone is not enough: the mounted transport needs the
        # server itself, and this pair is the reason the condition is an `and`.
        (False, True, False),
        (True, True, True),
    ],
)
def test_the_mount_needs_both_flags(mcp_enabled, mount_enabled, expected):
    with (
        patch.object(main_mod.settings, "mcp_enabled", mcp_enabled),
        patch.object(main_mod.settings, "mcp_mount_enabled", mount_enabled),
    ):
        assert main_mod.should_mount_mcp() is expected


def test_the_running_app_agrees_with_the_decision():
    """The flags and the routes are the same fact, read two ways."""
    assert _routes_contain_mcp(main_mod.app) is main_mod.should_mount_mcp()
