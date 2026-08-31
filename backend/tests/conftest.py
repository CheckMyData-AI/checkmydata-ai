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


@pytest.fixture(autouse=True)
def _entitlements_are_process_global():
    """Reset the entitlement provider around every test.

    `app.entitlements` holds one provider for the process, which is right in production —
    it is installed once at start-up — and a hazard in a suite, where a test that installs
    a refusing provider and does not reset leaves every later test facing a 402 it never
    asked for.

    Added after exactly that: one integration test failed in a full run and passed alone,
    and the tempting reading was "flaky". A global with a hand-written reset in three
    files is not flaky, it is unfinished — so the reset moved here, where forgetting it is
    not possible.
    """
    from app.entitlements import reset_entitlements

    reset_entitlements()
    yield
    reset_entitlements()
