"""Unit tests for app.config Settings validators."""

import logging
import os
import re
from pathlib import Path
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
                debug=False,
                jwt_secret="change-me-in-production",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
            )

    def test_production_rejects_empty_encryption_key(self):
        with pytest.raises(Exception, match="MASTER_ENCRYPTION_KEY"):
            Settings(
                environment="production",
                debug=False,
                jwt_secret="a-secure-jwt-secret-that-is-long-enough-32",
                master_encryption_key="",
            )

    def test_non_production_allows_defaults(self):
        s = Settings(environment="development")
        assert s.environment == "development"

    def test_unknown_environment_fails_closed(self):
        # F-AUTH-11: any env that isn't an explicit dev/test name is treated as prod,
        # so a missing/mistyped ENVIRONMENT can't boot with the default JWT secret.
        for env in ("staging", "prod-eu", "live", "", "typo"):
            with pytest.raises(Exception, match="JWT_SECRET"):
                Settings(
                    environment=env,
                    debug=False,
                    jwt_secret="change-me-in-production",
                    master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
                )

    def test_unset_environment_fails_closed(self):
        # S-04: with ENVIRONMENT unset, the field default must behave as
        # production — the guard rejects the default JWT secret instead of
        # silently relaxing into development.
        env = {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(Exception, match="JWT_SECRET"):
                Settings(_env_file=None)

    def test_unset_environment_defaults_to_production(self):
        env = {k: v for k, v in os.environ.items() if k != "ENVIRONMENT"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings(
                _env_file=None,
                jwt_secret="a-secure-jwt-secret-32-characters-long-or-more",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
            )
        assert s.environment == "production"

    def test_explicit_dev_envs_allow_defaults(self):
        for env in ("development", "dev", "test", "testing", "local", "ci"):
            s = Settings(environment=env, jwt_secret="change-me-in-production")
            assert s.environment == env


class TestSameSiteNoneRequiresSecure:
    """F-AUTH-08: SameSite=None cookies must also be Secure or browsers drop them."""

    def test_samesite_none_without_secure_raises(self):
        with pytest.raises(Exception, match="SAMESITE"):
            Settings(auth_cookie_samesite="none", auth_cookie_secure=False)

    def test_samesite_none_with_secure_ok(self):
        s = Settings(auth_cookie_samesite="none", auth_cookie_secure=True)
        assert s.auth_cookie_samesite == "none"

    def test_samesite_lax_without_secure_ok(self):
        s = Settings(auth_cookie_samesite="lax", auth_cookie_secure=False)
        assert s.auth_cookie_samesite == "lax"

    def test_production_rejects_short_jwt(self):
        with pytest.raises(Exception, match="at least 32"):
            Settings(
                environment="production",
                debug=False,
                jwt_secret="too-short",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
            )

    def test_production_rejects_debug_true(self):
        with pytest.raises(Exception, match="DEBUG"):
            Settings(
                environment="production",
                debug=True,
                jwt_secret="a-secure-jwt-secret-32-characters-long-or-more",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
            )

    def test_production_rejects_wildcard_cors(self):
        with pytest.raises(Exception, match="CORS"):
            Settings(
                environment="production",
                debug=False,
                jwt_secret="a-secure-jwt-secret-32-characters-long-or-more",
                master_encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Ng==",
                cors_origins=["*"],
            )


class TestNumericRangeValidation:
    def test_invalid_learning_mode_rejected(self):
        with pytest.raises(Exception, match="LEARNING_ANALYZER_MODE"):
            Settings(learning_analyzer_mode="bogus")

    def test_invalid_default_provider_rejected(self):
        with pytest.raises(Exception, match="DEFAULT_LLM_PROVIDER"):
            Settings(default_llm_provider="cohere")

    def test_invalid_synthesis_pct_rejected(self):
        with pytest.raises(Exception, match="AGENT_EMERGENCY_SYNTHESIS_PCT"):
            Settings(agent_emergency_synthesis_pct=1.5)

    def test_invalid_dedup_threshold_rejected(self):
        with pytest.raises(Exception, match="TOOL_DEDUP_SEMANTIC_THRESHOLD"):
            Settings(tool_dedup_semantic_threshold=2.0)

    def test_invalid_ssh_host_key_policy_rejected(self):
        with pytest.raises(Exception, match="SSH_HOST_KEY_POLICY"):
            Settings(ssh_host_key_policy="auto_add")

    def test_valid_ssh_host_key_policies_accepted(self):
        for policy in ("disabled", "tofu", "strict"):
            assert Settings(ssh_host_key_policy=policy).ssh_host_key_policy == policy

    def test_negative_result_corrections_rejected(self):
        with pytest.raises(Exception, match="ORCHESTRATOR_MAX_RESULT_CORRECTIONS"):
            Settings(orchestrator_max_result_corrections=-1)


class TestSplitDomainCookieGuardrail:
    """The startup warning that catches the split-domain cookie outage."""

    def test_warns_when_domain_empty_with_remote_https_origin(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            Settings(
                auth_cookie_enabled=True,
                auth_cookie_secure=True,
                auth_cookie_domain="",
                cors_origins=["https://app.example.com"],
            )
        assert any("AUTH_COOKIE_DOMAIN is empty" in r.message for r in caplog.records)

    def test_silent_for_localhost_only_origins(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            Settings(
                auth_cookie_enabled=True,
                auth_cookie_secure=True,
                auth_cookie_domain="",
                cors_origins=["http://localhost:3000", "http://127.0.0.1:3100"],
            )
        assert not any("AUTH_COOKIE_DOMAIN is empty" in r.message for r in caplog.records)

    def test_silent_when_domain_configured(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            Settings(
                auth_cookie_enabled=True,
                auth_cookie_secure=True,
                auth_cookie_domain=".example.com",
                cors_origins=["https://app.example.com"],
            )
        assert not any("AUTH_COOKIE_DOMAIN is empty" in r.message for r in caplog.records)

    def test_silent_when_cookies_disabled(self, caplog):
        with caplog.at_level(logging.WARNING, logger="app.config"):
            Settings(
                auth_cookie_enabled=False,
                auth_cookie_secure=True,
                auth_cookie_domain="",
                cors_origins=["https://app.example.com"],
            )
        assert not any("AUTH_COOKIE_DOMAIN is empty" in r.message for r in caplog.records)


# Internal helpers / properties that are not user-tunable env vars and
# therefore should not be required to appear in .env.example.
_NON_ENV_FIELDS: set[str] = {"agent"}


def _load_env_example_keys() -> set[str]:
    """Parse backend/.env.example, returning every uppercase KEY mentioned.

    We accept both active assignments (``KEY=value``) and commented-out
    knobs (``# KEY=value``) so the example doc can keep advanced settings
    discoverable without forcing them into the active environment.
    """

    env_path = Path(__file__).resolve().parents[2] / ".env.example"
    text = env_path.read_text()
    pattern = re.compile(r"^[#\s]*([A-Z][A-Z0-9_]+)\s*=", re.MULTILINE)
    return {m.group(1) for m in pattern.finditer(text)}


class TestEnvExampleSync:
    """Guards against drift between Settings fields and .env.example (T35).

    Every Settings field (other than ``_NON_ENV_FIELDS`` and computed
    properties) must appear in ``.env.example``, even if commented out, so
    operators have a single source of truth for available knobs.
    """

    def test_every_settings_field_documented(self) -> None:
        documented = _load_env_example_keys()
        missing: list[str] = []

        for field_name in Settings.model_fields:
            if field_name in _NON_ENV_FIELDS:
                continue
            if field_name.upper() not in documented:
                missing.append(field_name)

        assert not missing, (
            "Settings fields missing from backend/.env.example "
            f"(add them, even commented): {sorted(missing)}"
        )
