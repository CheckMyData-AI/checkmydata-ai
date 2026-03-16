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
