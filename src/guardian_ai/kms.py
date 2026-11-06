"""ShieldAI KMS - local key management.

Resolution order for a service key (all storage stays on this machine):

  1. Environment variable SHIELDAI_KEY_<SERVICE> (base64 or hex, 32 bytes)
     or the shared SHIELDAI_KEY.
  2. Windows DPAPI-protected key file under .shield_keys/ (per-user,
     no master password needed; the blob is useless on another machine
     or another user account).
  3. On non-Windows: a key file with owner-only permissions (0600).

If no key exists, a fresh 32-byte key is generated and persisted.
"""
import base64
import binascii
import os
import secrets
from pathlib import Path
from typing import Optional

from guardian_ai.paths import data_dir

_KEY_BYTES = 32


def _key_dir() -> Path:
    return data_dir() / ".shield_keys"


def _env_key(service_name: str) -> Optional[bytes]:
    for var in (f"SHIELDAI_KEY_{service_name.upper()}", "SHIELDAI_KEY"):
        raw = os.environ.get(var)
        if not raw:
            continue
        try:
            key = base64.b64decode(raw, validate=True)
        except (binascii.Error, ValueError):
            try:
                key = bytes.fromhex(raw)
            except ValueError:
                continue
        if len(key) == _KEY_BYTES:
            return key
    return None


def _dpapi(data: bytes, protect: bool) -> bytes:
    """Windows DPAPI via crypt32. Raises OSError when unavailable."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    func = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    func.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR,
                     ctypes.POINTER(DATA_BLOB), wintypes.LPVOID,
                     wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(DATA_BLOB)]
    func.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    in_buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    if not func(ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)):
        raise OSError(f"DPAPI {'protect' if protect else 'unprotect'} failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _read_key_file(path: Path) -> Optional[bytes]:
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    if os.name == "nt":
        try:
            raw = _dpapi(blob, protect=False)
        except OSError:
            return None
    else:
        raw = blob
    return raw if len(raw) == _KEY_BYTES else None


def _write_key_file(path: Path, key: bytes) -> None:
    _key_dir().mkdir(parents=True, exist_ok=True)
    blob = _dpapi(key, protect=True) if os.name == "nt" else key
    path.write_bytes(blob)
    if os.name != "nt":
        os.chmod(path, 0o600)


def get_key(service_name: str) -> bytes:
    """Return the persistent 32-byte key for a service, creating it if needed."""
    key = _env_key(service_name)
    if key:
        return key

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in service_name)
    path = _key_dir() / f"{safe_name}.key"
    key = _read_key_file(path)
    if key is None:
        key = secrets.token_bytes(_KEY_BYTES)
        try:
            _write_key_file(path, key)
        except OSError:
            pass  # ephemeral key; still functional within this process
    return key


__all__ = ["get_key"]
