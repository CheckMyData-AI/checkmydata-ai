from app.config import settings


def test_mcp_mount_defaults_off():
    assert settings.mcp_mount_enabled is False
    assert settings.mcp_mount_path == "/mcp"
