import importlib
from unittest.mock import patch


def _routes_contain_mcp(app) -> bool:
    return any(getattr(r, "path", "").startswith("/mcp") for r in app.routes)


def test_mount_absent_when_flag_off():
    import app.main as main_mod

    with patch.object(main_mod.settings, "mcp_mount_enabled", False):
        importlib.reload(main_mod)
    assert not _routes_contain_mcp(main_mod.app)
    importlib.reload(main_mod)  # restore default module state


def test_mount_present_when_flags_on():
    import app.main as main_mod

    with (
        patch.object(main_mod.settings, "mcp_enabled", True),
        patch.object(main_mod.settings, "mcp_mount_enabled", True),
    ):
        importlib.reload(main_mod)
        assert _routes_contain_mcp(main_mod.app)
    importlib.reload(main_mod)  # restore default module state
