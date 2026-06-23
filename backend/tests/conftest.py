import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
# The harness authenticates via Bearer tokens read from the register/login response
# body. Under cookie auth the JWT is omitted from the body (F-AUTH-04), so the suite
# runs in Bearer mode by default; cookie-specific tests opt into cookie auth explicitly.
os.environ.setdefault("AUTH_COOKIE_ENABLED", "false")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply 'unit' or 'integration' markers based on test file location."""
    for item in items:
        path = Path(item.fspath)
        parts = path.parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        elif "integration" in parts:
            item.add_marker(pytest.mark.integration)
