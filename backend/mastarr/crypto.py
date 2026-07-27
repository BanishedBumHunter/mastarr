"""Encryption for *arr API keys at rest.

Keys live in SQLite, which sits on a mounted volume that is trivially readable by anyone
with filesystem access. Fernet gives us authenticated symmetric encryption; the Fernet key
itself is kept out of the DB, in the environment or a 0600 file beside it.
"""

from __future__ import annotations

import stat

from cryptography.fernet import Fernet, InvalidToken

from .config import Settings


class DecryptionError(RuntimeError):
    """Stored ciphertext could not be decrypted with the current secret key."""


def load_or_create_key(settings: Settings) -> bytes:
    """Resolve the Fernet key: env first, then a 0600 file, generating one if neither exists.

    Generating on first run means a fresh deployment works with no setup, but the key must
    then survive restarts or every stored API key becomes unreadable — hence persisting it
    to the data volume rather than holding it in memory.
    """
    if settings.secret_key:
        return settings.secret_key.encode()

    key_file = settings.data_dir / "secret.key"
    if key_file.is_file():
        return key_file.read_bytes().strip()

    key = Fernet.generate_key()
    key_file.write_bytes(key)
    key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return key


class KeyCipher:
    """Encrypts/decrypts *arr API keys. Never logs, never raises with plaintext attached."""

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            # Deliberately opaque: the message reaches logs and API responses.
            raise DecryptionError(
                "Stored API key could not be decrypted. The secret key has likely "
                "changed since it was saved; re-enter the key for this service."
            ) from exc


_cipher: KeyCipher | None = None


def get_cipher(settings: Settings | None = None) -> KeyCipher:
    global _cipher
    if _cipher is None:
        from .config import get_settings

        resolved = settings or get_settings()
        _cipher = KeyCipher(load_or_create_key(resolved))
    return _cipher


def reset_cipher() -> None:
    """Test hook — drops the cached cipher so a new settings object takes effect."""
    global _cipher
    _cipher = None


__all__ = [
    "DecryptionError",
    "KeyCipher",
    "get_cipher",
    "load_or_create_key",
    "reset_cipher",
]
