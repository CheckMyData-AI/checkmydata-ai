from app.config import settings


def test_reaper_flag_defaults():
    assert settings.reaper_enabled is True
    assert settings.heartbeat_interval_seconds == 30
    assert settings.reaper_interval_seconds == 60
    assert settings.stale_running_heartbeat_timeout_seconds == 300
