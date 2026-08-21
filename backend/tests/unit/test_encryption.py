from app.services.encryption import decrypt, encrypt


class TestEncryption:
    def test_round_trip(self):
        plaintext = "my_secret_password"
        encrypted = encrypt(plaintext)
        assert encrypted != plaintext
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext

    def test_different_ciphertexts(self):
        plain = "test"
        e1 = encrypt(plain)
        e2 = encrypt(plain)
        # Fernet uses unique IV each time, so ciphertexts differ
        assert e1 != e2

    def test_empty_string(self):
        encrypted = encrypt("")
        assert decrypt(encrypted) == ""


class TestDecryptionFailure:
    def test_bad_ciphertext_raises(self):
        import pytest

        with pytest.raises(Exception):
            decrypt("this-is-not-valid-fernet-ciphertext")


class TestMissingKey:
    def test_no_encryption_key_raises(self):
        # F-CONN-05 replaced the single `_fernet` global with a primary + reader pair
        # behind `reset_cache()`; the assertion — an absent key must be a loud
        # RuntimeError naming the variable — is unchanged.
        from unittest.mock import patch

        import pytest

        from app.services import encryption

        encryption.reset_cache()
        try:
            with patch("app.services.encryption.settings") as mock_settings:
                mock_settings.master_encryption_key = ""
                mock_settings.master_encryption_keys_old = ""
                with pytest.raises(RuntimeError, match="MASTER_ENCRYPTION_KEY"):
                    encryption.encrypt("x")
        finally:
            encryption.reset_cache()


# ---------------------------------------------------------------------------
# F-CONN-05: a single Fernet key with no way to retire it
# ---------------------------------------------------------------------------


class TestKeyRotation:
    """Before this there was one key and no path off it.

    A leaked ``MASTER_ENCRYPTION_KEY`` could only be replaced by re-encrypting every
    secret by hand, and swapping it outright makes every stored credential
    permanently unreadable — so in practice the key was never rotated at all.
    """

    @staticmethod
    def _reset(monkeypatch, primary: str, old: str = "") -> None:
        import app.services.encryption as enc
        from app.config import settings

        monkeypatch.setattr(settings, "master_encryption_key", primary, raising=False)
        monkeypatch.setattr(settings, "master_encryption_keys_old", old, raising=False)
        enc.reset_cache()

    @staticmethod
    def _key() -> str:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()

    def test_a_token_from_a_retired_key_still_decrypts(self, monkeypatch):
        from app.services.encryption import decrypt, encrypt

        old_key = self._key()
        self._reset(monkeypatch, old_key)
        token = encrypt("db-password")

        new_key = self._key()
        self._reset(monkeypatch, new_key, old=old_key)

        assert decrypt(token) == "db-password", (
            "rotating the primary key must not orphan already-stored secrets"
        )

    def test_new_writes_use_the_primary_key_only(self, monkeypatch):
        from cryptography.fernet import Fernet, InvalidToken

        from app.services.encryption import encrypt

        old_key = self._key()
        new_key = self._key()
        self._reset(monkeypatch, new_key, old=old_key)
        token = encrypt("fresh")

        assert Fernet(new_key.encode()).decrypt(token.encode()).decode() == "fresh"
        try:
            Fernet(old_key.encode()).decrypt(token.encode())
        except InvalidToken:
            pass
        else:
            raise AssertionError("a retired key must not be able to read a new token")

    def test_is_on_primary_key_tells_the_two_apart(self, monkeypatch):
        """The retirement question — "can I drop the old key yet?" — needs this."""
        from app.services.encryption import encrypt, is_on_primary_key

        old_key = self._key()
        self._reset(monkeypatch, old_key)
        legacy = encrypt("old")

        new_key = self._key()
        self._reset(monkeypatch, new_key, old=old_key)
        fresh = encrypt("new")

        assert is_on_primary_key(fresh) is True
        assert is_on_primary_key(legacy) is False

    def test_rotate_token_moves_it_onto_the_primary_key(self, monkeypatch):
        from app.services.encryption import decrypt, encrypt, is_on_primary_key, rotate_token

        old_key = self._key()
        self._reset(monkeypatch, old_key)
        legacy = encrypt("secret")

        new_key = self._key()
        self._reset(monkeypatch, new_key, old=old_key)
        moved = rotate_token(legacy)

        assert is_on_primary_key(moved) is True
        assert decrypt(moved) == "secret", "rotation must not change what the token means"

    def test_several_retired_keys_are_all_accepted(self, monkeypatch):
        """Two rotations before a sweep completes is a normal state, not an error."""
        from app.services.encryption import decrypt, encrypt

        k1, k2, k3 = self._key(), self._key(), self._key()
        self._reset(monkeypatch, k1)
        t1 = encrypt("one")
        self._reset(monkeypatch, k2, old=k1)
        t2 = encrypt("two")
        self._reset(monkeypatch, k3, old=f"{k2},{k1}")

        assert decrypt(t1) == "one"
        assert decrypt(t2) == "two"
        assert decrypt(encrypt("three")) == "three"

    def test_whitespace_in_the_old_key_list_is_tolerated(self, monkeypatch):
        from app.services.encryption import decrypt, encrypt

        k1, k2 = self._key(), self._key()
        self._reset(monkeypatch, k1)
        t1 = encrypt("one")
        self._reset(monkeypatch, k2, old=f"  {k1} ,  ")
        assert decrypt(t1) == "one"

    def test_a_malformed_old_key_is_refused_loudly(self, monkeypatch):
        """A mistyped retired key that silently does nothing is how a rotation
        'succeeds' while leaving rows no one can read."""
        import pytest

        self._reset(monkeypatch, self._key(), old="not-a-fernet-key")
        with pytest.raises(Exception) as exc:
            from app.services.encryption import encrypt

            encrypt("x")
        assert "MASTER_ENCRYPTION_KEYS_OLD" in str(exc.value)

    def test_the_fingerprint_never_contains_the_key(self, monkeypatch):
        from app.services.encryption import key_fingerprint

        primary = self._key()
        self._reset(monkeypatch, primary)
        fp = key_fingerprint()
        assert fp and primary not in fp
        assert len(fp) <= 32
