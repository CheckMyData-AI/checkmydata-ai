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
        from unittest.mock import patch

        import pytest

        from app.services import encryption

        old_fernet = encryption._fernet
        encryption._fernet = None
        try:
            with patch("app.services.encryption.settings") as mock_settings:
                mock_settings.master_encryption_key = ""
                with pytest.raises(RuntimeError, match="MASTER_ENCRYPTION_KEY"):
                    encryption._get_fernet()
        finally:
            encryption._fernet = old_fernet
