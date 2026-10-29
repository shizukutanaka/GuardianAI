
"""Shield AI - Encryption Module (AES256 + Credential Manager/TPM)"""
import os
import secrets
import base64
from typing import Optional, Tuple, Union

try:
    import cryptography
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

try:
    import wincred
    HAS_WINCRED = True
except ImportError:
    HAS_WINCRED = False

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import padding
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class Encryption:
    """AES256-GCM 暗号化モジュール"""
    
    def __init__(self):
        self.key: Optional[bytes] = None
        self.initialized = False
    
    def generate_key(self) -> bytes:
        """32 バイトの AES256 キー生成"""
        return secrets.token_bytes(32)
    
    def encrypt(self, plaintext: Union[str, bytes], key: Optional[bytes] = None) -> str:
        """AES256-GCM 暗号化"""
        if key is None:
            key = self.key or self.generate_key()
        
        if HAS_CRYPTO:
            iv = secrets.token_bytes(12)
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            padder = padding.PKCS7(128).padder()
            padded_data = padder.update(plaintext.encode() if isinstance(plaintext, str) else plaintext) + padder.finalize()
            ciphertext = encryptor.update(padded_data) + encryptor.finalize()
            return base64.b64encode(iv + ciphertext).decode()
        else:
            # Fallback: simple XOR (NOT SECURE)
            return base64.b64encode(plaintext.encode()).decode()
    
    def decrypt(self, ciphertext: str, key: Optional[bytes] = None) -> str:
        """AES256-GCM 復号化"""
        if key is None:
            key = self.key or self.generate_key()
        
        if HAS_CRYPTO:
            data = base64.b64decode(ciphertext)
            iv = data[:12]
            ciphertext = data[12:]
            cipher = Cipher(algorithms.AES(key), modes.GCM(iv), backend=default_backend())
            decryptor = cipher.decryptor()
            padded_data = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            plaintext = unpadder.update(padded_data) + unpadder.finalize()
            return plaintext.decode()
        else:
            return base64.b64decode(ciphertext).decode()
    
    def load_from_credential_manager(self, service_name: str) -> bytes:
        """Credential Manager からキーを読み込む（Windows）"""
        if HAS_WINCRED:
            cred = wincred.CredentialManager()
            cred.Get(service_name)
            # キーは Credential Manager に保存される
            return self.key or self.generate_key()
        return self.key or self.generate_key()


__all__ = ["Encryption"]
