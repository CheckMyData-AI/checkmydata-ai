from app.config import Settings


def test_mcp_mount_defaults_off():
    # Use a fresh Settings() instance so the test is not affected by env vars
    # loaded into the module-level singleton by other tests or the test runner.
    s = Settings()
    assert s.mcp_mount_enabled is False
    assert s.mcp_mount_path == "/mcp"
