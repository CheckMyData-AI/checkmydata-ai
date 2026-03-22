"""Unit tests for app.config Settings validators."""

import os
from unittest.mock import patch

import pytest

from app.config import Settings


class TestFixDatabaseUrl:
    def test_postgres_url_rewritten(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host/db"}, clear=False):
            s = Settings(database_url="postgres://user:pass@host/db")
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_postgresql_url_rewritten(self):
        env = {"DATABASE_URL": "postgresql://user:pass@host/db"}
        with patch.dict(os.environ, env, clear=False):
            s = Settings(database_url="postgresql://user:pass@host/db")
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_sqlite_url_unchanged(self):
        s = Settings(database_url="sqlite+aiosqlite:///:memory:")
        assert s.database_url == "sqlite+aiosqlite:///:memory:"


class TestProductionValidation:
    def test_production_rejects_default_jwt(self):
        with pytest.raises(Exception, match="JWT_SECRET"):
            Settings(
                environment="production",
                jwt_secret="change-me-in-production",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
            )

    def test_production_rejects_empty_encryption_key(self):
        with pytest.raises(Exception, match="MASTER_ENCRYPTION_KEY"):
            Settings(
                environment="production",
                jwt_secret="a-secure-secret-that-is-long-enough",
                master_encryption_key="",
            )

    def test_non_production_allows_defaults(self):
        s = Settings(environment="development")
        assert s.environment == "development"
