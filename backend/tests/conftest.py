import os

from cryptography.fernet import Fernet

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MASTER_ENCRYPTION_KEY", Fernet.generate_key().decode())
