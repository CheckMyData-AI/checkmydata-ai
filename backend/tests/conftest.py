import os
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
# Settings defaults ENVIRONMENT to "production" (fail-closed, S-04); the suite
# must opt into a safe test environment or every app.config import would trip
# the production secret guard.
os.environ.setdefault("ENVIRONMENT", "test")
# The harness authenticates via Bearer tokens read from the register/login response
# body. Under cookie auth the JWT is omitted from the body (F-AUTH-04), so the suite
# runs in Bearer mode by default; cookie-specific tests opt into cookie auth explicitly.
os.environ.setdefault("AUTH_COOKIE_ENABLED", "false")


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_app_engine():
    """Dispose the global app engine before the session event loop closes.

    Tests that exercise the real ``app.models.base.async_session_factory`` open
    aiosqlite connections on the module-level ``engine`` that nothing else tears
    down. With a session-scoped loop those connections' worker threads outlive
    individual tests; when the loop finally closes, the daemon thread calls
    ``call_soon_threadsafe`` on it and pytest surfaces a
    ``PytestUnhandledThreadExceptionWarning: RuntimeError: Event loop is closed``.
    Disposing here closes those connections while the loop is still running.
    """
    yield
    from app.models import base as base_mod

    await base_mod.engine.dispose()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply 'unit' or 'integration' markers based on test file location."""
    for item in items:
        path = Path(item.fspath)
        parts = path.parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)
