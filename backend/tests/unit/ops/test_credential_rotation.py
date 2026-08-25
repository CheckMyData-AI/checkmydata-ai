"""F-CONN-05: sweeping stored secrets onto the current primary key.

Rotation is only finished when the old key can be dropped, and that is a property of
the *rows*, not of the config. A sweep that misses one column means the old key must
be kept forever while the config says the rotation is done — so the coverage of the
six encrypted columns is asserted structurally as well as behaviourally.
"""

import uuid

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import app.models.connection  # noqa: F401
import app.models.deploy_state  # noqa: F401
import app.models.project  # noqa: F401
import app.models.repository  # noqa: F401
import app.models.ssh_key  # noqa: F401
import app.models.user  # noqa: F401
import app.models.vendor_credential  # noqa: F401
import app.services.encryption as enc
from app.models.base import Base
from app.models.connection import Connection
from app.models.project import Project
from app.models.ssh_key import SshKey
from app.models.user import User
from app.models.vendor_credential import VendorCredential


@pytest_asyncio.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _key() -> str:
    return Fernet.generate_key().decode()


def _use(monkeypatch, primary: str, old: str = "") -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "master_encryption_key", primary, raising=False)
    monkeypatch.setattr(settings, "master_encryption_keys_old", old, raising=False)
    enc.reset_cache()


def _encrypted_column_count() -> int:
    """How many encrypted columns the sweep actually carries — computed, not typed.

    The assertions below were written as `== 7`. Dropping one dead column
    (`ProjectRepository.auth_token_encrypted`, F-REPO-04) turned four of them red for a
    reason that had nothing to do with what they test, and the tempting repair is to
    edit a 7 into a 6 in four places. That is the same shape as the board tally that
    claimed four different numbers at once: a figure maintained by hand, in more than
    one place, read as if it were measured.
    """
    from app.ops.credential_rotation import ENCRYPTED_COLUMNS

    return sum(len(fields) for _model, fields in ENCRYPTED_COLUMNS)


async def _seed_every_encrypted_column(factory) -> None:
    """One value per encrypted column, written under whatever key is active.

    `ProjectRepository.auth_token_encrypted` used to be seeded here — the sweep carried
    it although nothing wrote it. The column was dropped in `6287a47828ca` (F-REPO-04)
    after production was measured empty, so the sweep no longer has it to reach. The
    derived-coverage assertion below is what keeps this fixture honest either way: it
    compares the sweep's map against every mapped `_encrypted` column, so a column
    added or removed shows up here rather than being remembered.
    """
    async with factory() as s:
        u = User(email=f"u-{uuid.uuid4().hex[:6]}@t.com", password_hash="x", display_name="T")
        s.add(u)
        await s.flush()
        p = Project(name="p", owner_id=u.id)
        s.add(p)
        await s.flush()
        s.add(
            Connection(
                project_id=p.id,
                name="c",
                db_type="postgres",
                db_password_encrypted=enc.encrypt("pw"),
                connection_string_encrypted=enc.encrypt("postgres://x"),
                mcp_env_encrypted=enc.encrypt('{"A":"1"}'),
            )
        )
        s.add(
            SshKey(
                user_id=u.id,
                name="k",
                private_key_encrypted=enc.encrypt("PRIVATE"),
                passphrase_encrypted=enc.encrypt("phrase"),
                fingerprint="fp",
                key_type="ed25519",
            )
        )
        s.add(
            VendorCredential(
                user_id=u.id,
                name="v",
                provider="ga4",
                secret_encrypted=enc.encrypt("vendor-secret"),
                fingerprint="vfp",
            )
        )
        await s.commit()


class TestRotationSweep:
    @pytest.mark.asyncio
    async def test_every_encrypted_column_moves_onto_the_new_key(self, factory, monkeypatch):
        from app.ops.credential_rotation import pending_rotation_count, rotate_credentials

        old = _key()
        _use(monkeypatch, old)
        await _seed_every_encrypted_column(factory)

        new = _key()
        _use(monkeypatch, new, old=old)

        async with factory() as s:
            assert await pending_rotation_count(s) == _encrypted_column_count(), (
                "every one starts on the retired key"
            )

        result = await rotate_credentials(session_factory=factory)
        assert result.rotated == _encrypted_column_count()

        async with factory() as s:
            assert await pending_rotation_count(s) == 0, (
                "a non-zero remainder means the retired key can never be dropped"
            )

    @pytest.mark.asyncio
    async def test_the_secrets_still_mean_the_same_thing(self, factory, monkeypatch):
        from app.ops.credential_rotation import rotate_credentials

        old = _key()
        _use(monkeypatch, old)
        await _seed_every_encrypted_column(factory)
        new = _key()
        _use(monkeypatch, new, old=old)
        await rotate_credentials(session_factory=factory)

        # The retired key is gone entirely: if a value had been re-encrypted wrongly,
        # or skipped, this is where it stops being readable.
        _use(monkeypatch, new)
        async with factory() as s:
            conn = (await s.scalars(__import__("sqlalchemy").select(Connection))).one()
            key = (await s.scalars(__import__("sqlalchemy").select(SshKey))).one()
            cred = (await s.scalars(__import__("sqlalchemy").select(VendorCredential))).one()
        assert enc.decrypt(conn.db_password_encrypted) == "pw"
        assert enc.decrypt(conn.connection_string_encrypted) == "postgres://x"
        assert enc.decrypt(conn.mcp_env_encrypted) == '{"A":"1"}'
        assert enc.decrypt(key.private_key_encrypted) == "PRIVATE"
        assert enc.decrypt(key.passphrase_encrypted) == "phrase"
        assert enc.decrypt(cred.secret_encrypted) == "vendor-secret"

    @pytest.mark.asyncio
    async def test_rows_already_on_the_primary_key_are_left_alone(self, factory, monkeypatch):
        """Idempotent, and cheap on the second run: nothing is rewritten needlessly."""
        from app.ops.credential_rotation import rotate_credentials

        new = _key()
        _use(monkeypatch, new)
        await _seed_every_encrypted_column(factory)

        result = await rotate_credentials(session_factory=factory)
        assert result.rotated == 0
        assert result.examined == _encrypted_column_count()

    @pytest.mark.asyncio
    async def test_a_second_sweep_changes_nothing(self, factory, monkeypatch):
        from app.ops.credential_rotation import rotate_credentials

        old = _key()
        _use(monkeypatch, old)
        await _seed_every_encrypted_column(factory)
        _use(monkeypatch, _key(), old=old)

        first = await rotate_credentials(session_factory=factory)
        second = await rotate_credentials(session_factory=factory)
        assert first.rotated == _encrypted_column_count()
        assert second.rotated == 0

    @pytest.mark.asyncio
    async def test_a_null_column_is_not_counted_as_pending(self, factory, monkeypatch):
        from app.ops.credential_rotation import pending_rotation_count

        old = _key()
        _use(monkeypatch, old)
        async with factory() as s:
            u = User(email=f"u-{uuid.uuid4().hex[:6]}@t.com", password_hash="x", display_name="T")
            s.add(u)
            await s.flush()
            p = Project(name="p", owner_id=u.id)
            s.add(p)
            await s.flush()
            # Nothing encrypted at all: an optional secret nobody set.
            s.add(Connection(project_id=p.id, name="c", db_type="postgres"))
            await s.commit()
        _use(monkeypatch, _key(), old=old)
        async with factory() as s:
            assert await pending_rotation_count(s) == 0


class TestSweepCoversEveryEncryptedColumn:
    def test_the_sweep_names_every_column_written_through_encrypt(self) -> None:
        """A column added later and not added here is silently never rotated.

        Enumerated tests cannot find what was forgotten, so the set is derived: every
        model column whose name ends in `_encrypted` must appear in the sweep's map.
        """
        import app.models  # noqa: F401
        from app.models.base import Base as ModelBase
        from app.ops.credential_rotation import ENCRYPTED_COLUMNS

        declared = {
            (mapper.class_.__name__, col.key)
            for mapper in ModelBase.registry.mappers
            for col in mapper.columns
            if col.key.endswith("_encrypted")
        }
        swept = {(model.__name__, field) for model, fields in ENCRYPTED_COLUMNS for field in fields}
        assert declared == swept, (
            f"declared but never rotated: {sorted(declared - swept)}; "
            f"rotated but not declared: {sorted(swept - declared)}"
        )


class TestReconcileAtBoot:
    """Rotation must cost two config values and a deploy, not a script nobody runs."""

    @pytest.mark.asyncio
    async def test_a_first_ever_boot_only_seeds_the_marker(self, factory, monkeypatch):
        from app.ops.encryption_reconcile import reconcile_encryption_keys

        _use(monkeypatch, _key())
        await _seed_every_encrypted_column(factory)
        out = await reconcile_encryption_keys(session_factory=factory)
        assert out.status == "seeded"
        assert out.rotated == 0, "existing rows are already on the only key there has been"

    @pytest.mark.asyncio
    async def test_an_unchanged_key_does_no_work(self, factory, monkeypatch):
        from app.ops.encryption_reconcile import reconcile_encryption_keys

        _use(monkeypatch, _key())
        await _seed_every_encrypted_column(factory)
        await reconcile_encryption_keys(session_factory=factory)
        out = await reconcile_encryption_keys(session_factory=factory)
        assert out.status == "unchanged"

    @pytest.mark.asyncio
    async def test_a_changed_key_sweeps_and_advances_the_marker(self, factory, monkeypatch):
        from app.ops.credential_rotation import pending_rotation_count
        from app.ops.encryption_reconcile import reconcile_encryption_keys

        old = _key()
        _use(monkeypatch, old)
        await _seed_every_encrypted_column(factory)
        await reconcile_encryption_keys(session_factory=factory)  # seed

        _use(monkeypatch, _key(), old=old)
        out = await reconcile_encryption_keys(session_factory=factory)
        assert out.status == "rotated"
        assert out.rotated == _encrypted_column_count()
        async with factory() as s:
            assert await pending_rotation_count(s) == 0

        # Marker advanced, so a second boot is a no-op.
        again = await reconcile_encryption_keys(session_factory=factory)
        assert again.status == "unchanged"

    @pytest.mark.asyncio
    async def test_an_unreadable_row_leaves_the_marker_alone(self, factory, monkeypatch):
        """Saying the rotation is complete while a row is orphaned is the lie to avoid.

        The marker not advancing is what makes the next boot retry, and it is also what
        stops the operator being told they may drop the retired key.
        """
        from app.ops.encryption_reconcile import reconcile_encryption_keys

        old = _key()
        _use(monkeypatch, old)
        await _seed_every_encrypted_column(factory)
        await reconcile_encryption_keys(session_factory=factory)  # seed

        # A row encrypted under a key that is configured nowhere — a real state after a
        # botched manual rotation, and the one that must not be papered over.
        stranger = Fernet(_key().encode())
        async with factory() as s:
            import sqlalchemy

            cred = (await s.scalars(sqlalchemy.select(VendorCredential))).one()
            cred.secret_encrypted = stranger.encrypt(b"lost").decode()
            await s.commit()

        _use(monkeypatch, _key(), old=old)
        out = await reconcile_encryption_keys(session_factory=factory)
        assert out.status == "partial"
        assert out.failed == 1

        # Marker untouched → the next boot tries again rather than declaring success.
        retry = await reconcile_encryption_keys(session_factory=factory)
        assert retry.status == "partial"
