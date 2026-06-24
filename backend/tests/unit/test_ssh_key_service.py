from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - ensure all models registered on Base.metadata
import app.models.chat_session  # noqa: F401 - ensure all models resolved
import app.models.connection  # noqa: F401
import app.models.project  # noqa: F401
import app.models.ssh_key  # noqa: F401
from app.models.base import Base
from app.models.user import User
from app.services.ssh_key_service import SshKeyInUseError, SshKeyService

_test_key = asyncssh.generate_private_key("ssh-ed25519")
VALID_ED25519_KEY = _test_key.export_private_key("openssh").decode()


class TestSshKeyServiceValidation:
    def test_validate_valid_key(self):
        svc = SshKeyService()
        key_type, fingerprint = svc._validate_and_extract(VALID_ED25519_KEY, None)
        assert "ed25519" in key_type.lower() or "ssh-ed25519" in key_type.lower()
        assert len(fingerprint) > 0

    def test_validate_invalid_key(self):
        svc = SshKeyService()
        with pytest.raises(ValueError, match="Invalid SSH key"):
            svc._validate_and_extract("not a valid key", None)

    def test_validate_wrong_passphrase_on_encrypted_key(self):
        encrypted_key = _test_key.export_private_key("openssh", passphrase="correct").decode()
        svc = SshKeyService()
        with pytest.raises(ValueError):
            svc._validate_and_extract(encrypted_key, "wrong-passphrase")


class TestSshKeyServiceCRUD:
    @pytest.mark.asyncio
    async def test_create_and_list(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await svc.create(mock_session, "test-key", VALID_ED25519_KEY)
        assert result.name == "test-key"
        assert result.fingerprint
        assert "ed25519" in result.key_type.lower() or "ssh-ed25519" in result.key_type.lower()
        assert result.private_key_encrypted  # encrypted, not plaintext
        assert result.private_key_encrypted != VALID_ED25519_KEY
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_with_passphrase(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        result = await svc.create(mock_session, "pass-key", VALID_ED25519_KEY, passphrase=None)
        assert result.name == "pass-key"
        assert result.passphrase_encrypted is None

    @pytest.mark.asyncio
    async def test_get_decrypted(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        from app.services.encryption import encrypt

        mock_key.private_key_encrypted = encrypt(VALID_ED25519_KEY)
        mock_key.passphrase_encrypted = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_decrypted(mock_session, "key-123")
        assert result is not None
        key_content, passphrase = result
        assert key_content == VALID_ED25519_KEY.strip()
        assert passphrase is None

    @pytest.mark.asyncio
    async def test_get_decrypted_not_found(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get_decrypted(mock_session, "nonexistent")
        assert result is None


class TestSshKeyServiceGet:
    @pytest.mark.asyncio
    async def test_get_with_user_id(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.get(mock_session, "key-123", user_id="user-1")
        assert result is not None


class TestSshKeyServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_free_key(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        mock_key.name = "free-key"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.delete = AsyncMock()
        mock_session.commit = AsyncMock()

        with patch.object(svc, "_find_references", new_callable=AsyncMock, return_value=[]):
            deleted = await svc.delete(mock_session, "key-123")
        assert deleted is True
        mock_session.delete.assert_called_once_with(mock_key)

    @pytest.mark.asyncio
    async def test_delete_in_use_key(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        mock_key = MagicMock()
        mock_key.name = "used-key"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch.object(
            svc, "_find_references", new_callable=AsyncMock, return_value=["project:MyProject"]
        ):
            with pytest.raises(SshKeyInUseError) as exc_info:
                await svc.delete(mock_session, "key-123")
            assert "project:MyProject" in exc_info.value.references

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        deleted = await svc.delete(mock_session, "nonexistent")
        assert deleted is False


class TestSshKeyServiceListAll:
    @pytest.mark.asyncio
    async def test_list_all_no_filter(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_keys = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_keys
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.list_all(mock_session)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_all_with_user_id(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_keys = [MagicMock()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_keys
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await svc.list_all(mock_session, user_id="user-1")
        assert len(result) == 1


class TestSshKeyServiceDecryptFailure:
    @pytest.mark.asyncio
    async def test_decrypt_error_raises_value_error(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_key = MagicMock()
        mock_key.name = "bad-key"
        mock_key.private_key_encrypted = "corrupted-data"
        mock_key.passphrase_encrypted = None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_key
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.ssh_key_service.decrypt", side_effect=RuntimeError("bad")):
            with pytest.raises(ValueError, match="Cannot decrypt SSH key"):
                await svc.get_decrypted(mock_session, "key-123")


class TestSshKeyServiceFindReferences:
    @pytest.mark.asyncio
    async def test_find_references_empty(self):
        svc = SshKeyService()
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.__iter__ = lambda self: iter([])
        mock_session.execute = AsyncMock(return_value=mock_result)

        refs = await svc._find_references(mock_session, "key-123")
        assert refs == []

    @pytest.mark.asyncio
    async def test_find_references_with_projects_and_connections(self):
        svc = SshKeyService()
        mock_session = AsyncMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            # Order: projects, connections, repositories (R1-6).
            rows = {
                1: [("MyProject",)],
                2: [("MyConn",)],
                3: [("MyRepo",)],
            }.get(call_count, [])
            result.__iter__ = lambda self, _rows=rows: iter(_rows)
            return result

        mock_session.execute = mock_execute

        refs = await svc._find_references(mock_session, "key-123")
        assert "project:MyProject" in refs
        assert "connection:MyConn" in refs
        # R1-6: project_repositories must protect the key from deletion too.
        assert "repository:MyRepo" in refs


@pytest.fixture
async def db_session() -> AsyncSession:
    """Real in-memory SQLite session so the WHERE clause is actually executed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    s = sm()
    try:
        yield s
    finally:
        await s.close()
        await engine.dispose()


class TestSshKeyServiceTenantIsolation:
    """F-SSH-06 (C6): a NULL-owner key must never leak to a tenant.

    These tests run against a real DB session so the SQL ownership filter is
    genuinely exercised (mocked sessions cannot validate a WHERE clause).
    """

    @staticmethod
    async def _seed(session: AsyncSession) -> tuple[str, str]:
        """Seed user A, a NULL-owner key, and a key owned by A.

        Returns (null_key_id, a_key_id).
        """
        session.add(User(id="user-A", email="a@example.com"))
        await session.flush()

        svc = SshKeyService()
        # System/legacy key with no owner.
        null_key = await svc.create(session, "null-owner-key", VALID_ED25519_KEY, user_id=None)
        # Key owned by user A (distinct name; SSH key names are unique).
        a_key = await svc.create(
            session,
            "owned-by-A",
            _test_key.export_private_key("openssh").decode(),
            user_id="user-A",
        )
        return null_key.id, a_key.id

    @pytest.mark.asyncio
    async def test_list_all_excludes_null_owner_key(self, db_session: AsyncSession):
        null_key_id, a_key_id = await self._seed(db_session)
        svc = SshKeyService()

        keys = await svc.list_all(db_session, user_id="user-A")
        ids = {k.id for k in keys}

        assert a_key_id in ids  # A still sees their own key
        assert null_key_id not in ids  # the NULL-owner key must NOT leak to A

    @pytest.mark.asyncio
    async def test_get_null_owner_key_returns_none_for_user(self, db_session: AsyncSession):
        null_key_id, _a_key_id = await self._seed(db_session)
        svc = SshKeyService()

        result = await svc.get(db_session, null_key_id, user_id="user-A")
        assert result is None  # NULL-owner key is invisible to a scoped lookup

    @pytest.mark.asyncio
    async def test_get_own_key_still_returned_for_user(self, db_session: AsyncSession):
        _null_key_id, a_key_id = await self._seed(db_session)
        svc = SshKeyService()

        result = await svc.get(db_session, a_key_id, user_id="user-A")
        assert result is not None
        assert result.id == a_key_id

    @pytest.mark.asyncio
    async def test_system_path_still_resolves_by_id_when_user_id_none(
        self, db_session: AsyncSession
    ):
        """System/internal callers (user_id=None) keep resolving keys by id."""
        null_key_id, a_key_id = await self._seed(db_session)
        svc = SshKeyService()

        # Both the NULL-owner key and an owned key are reachable by id.
        assert (await svc.get(db_session, null_key_id, user_id=None)) is not None
        assert (await svc.get(db_session, a_key_id, user_id=None)) is not None
