"""ShieldAI Encryption - AES-256-GCM with authenticated key management.

Wire format: base64( iv(12) || ciphertext || tag(16) )

GCM is an authenticated stream mode: no padding is needed (PKCS7 was a
CBC leftover), and the tag is what makes tampering detectable. Decrypt
verifies the tag and raises ValueError on any mismatch.
"""
import base64
import secrets
from typing import Optional, Union

from guardian_ai.kms import get_key

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

_IV_LEN = 12
_TAG_LEN = 16


class Encryption:
    """AES-256-GCM encryption with a persistent local key."""

    def __init__(self, service_name: str = "shieldai"):
        if not HAS_CRYPTO:
            raise RuntimeError("cryptography package required: pip install cryptography")
        self.service_name = service_name
        self._key: Optional[bytes] = None

    @property
    def key(self) -> bytes:
        """Persistent key resolved through the KMS (env -> DPAPI -> key file)."""
        if self._key is None:
            self._key = get_key(self.service_name)
        return self._key

    def generate_key(self) -> bytes:
        """Generate a fresh 32-byte AES-256 key (not persisted)."""
        return secrets.token_bytes(32)

    def encrypt(self, plaintext: Union[str, bytes], key: Optional[bytes] = None) -> str:
        """AES-256-GCM encrypt; returns base64(iv || ciphertext || tag)."""
        key = key or self.key
        data = plaintext.encode() if isinstance(plaintext, str) else plaintext

        iv = secrets.token_bytes(_IV_LEN)
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(data) + encryptor.finalize()
        return base64.b64encode(iv + ciphertext + encryptor.tag).decode()

    def decrypt(self, ciphertext: str, key: Optional[bytes] = None) -> str:
        """AES-256-GCM decrypt. Raises ValueError if the tag does not verify."""
        key = key or self.key
        try:
            raw = base64.b64decode(ciphertext, validate=True)
        except Exception as e:
            raise ValueError(f"invalid ciphertext encoding: {e}") from e
        if len(raw) < _IV_LEN + _TAG_LEN:
            raise ValueError("ciphertext too short")

        iv, body, tag = raw[:_IV_LEN], raw[_IV_LEN:-_TAG_LEN], raw[-_TAG_LEN:]
        cipher = Cipher(algorithms.AES(key), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        try:
            data = decryptor.update(body) + decryptor.finalize()
        except Exception as e:
            raise ValueError(f"authentication failed: {e}") from e
        return data.decode()

    def load_from_credential_manager(self, service_name: str) -> bytes:
        """Load (or create) the key for a service via the KMS."""
        self.service_name = service_name
        self._key = None
        return self.key


__all__ = ["Encryption"]
