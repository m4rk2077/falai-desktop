"""Encrypted local storage for sensitive client files."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from src.utils.app_paths import ensure_app_data_dir
from src.utils.logger import get_logger

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except Exception:  # pragma: no cover - dependency is required at runtime
    AESGCM = None

try:
    from src.security.win_dpapi import protect_data, unprotect_data
except Exception:  # pragma: no cover - fallback only
    protect_data = None
    unprotect_data = None


logger = get_logger(__name__)


class LocalCryptoError(RuntimeError):
    """Raised on local encryption/decryption/migration failure."""


class LocalCrypto:
    """AES-256-GCM envelope encryption for local files."""

    MAGIC_V1 = b"FALAIv1"
    NONCE_SIZE = 12
    TAG_SIZE = 16

    def __init__(self, *, app_dir: Path | None = None):
        self.app_dir = Path(app_dir) if app_dir is not None else ensure_app_data_dir()
        self.key_path = self.app_dir / ".falai_local_dek"

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        aes = self._aesgcm()
        nonce = os.urandom(self.NONCE_SIZE)
        encrypted = aes.encrypt(nonce, bytes(plaintext or b""), None)
        ciphertext = encrypted[:-self.TAG_SIZE]
        tag = encrypted[-self.TAG_SIZE :]
        return self.MAGIC_V1 + nonce + ciphertext + tag

    def decrypt_bytes(self, payload: bytes) -> bytes:
        raw = bytes(payload or b"")
        if len(raw) < len(self.MAGIC_V1) + self.NONCE_SIZE + self.TAG_SIZE:
            raise LocalCryptoError("Encrypted payload is too small.")
        if not raw.startswith(self.MAGIC_V1):
            raise LocalCryptoError("Encrypted payload has invalid header.")
        body = raw[len(self.MAGIC_V1) :]
        nonce = body[: self.NONCE_SIZE]
        ciphertext = body[self.NONCE_SIZE : -self.TAG_SIZE]
        tag = body[-self.TAG_SIZE :]
        encrypted = ciphertext + tag
        aes = self._aesgcm()
        try:
            return aes.decrypt(nonce, encrypted, None)
        except Exception as exc:
            raise LocalCryptoError("Decrypt failed. Data is corrupted or key is unavailable.") from exc

    def read_json(self, path: Path, *, default: Any = None) -> Any:
        p = Path(path)
        if not p.exists():
            return default
        raw = p.read_bytes()
        plaintext = self.decrypt_bytes(raw)
        try:
            return json.loads(plaintext.decode("utf-8"))
        except Exception as exc:
            raise LocalCryptoError(f"Invalid JSON in encrypted file: {p}") from exc

    def write_json(self, path: Path, obj: Any) -> None:
        payload = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_bytes(path, payload)

    def read_bytes(self, path: Path) -> bytes:
        p = Path(path)
        if not p.exists():
            raise LocalCryptoError(f"Encrypted file not found: {p}")
        return self.decrypt_bytes(p.read_bytes())

    def write_bytes(self, path: Path, plaintext: bytes) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(self.encrypt_bytes(bytes(plaintext or b"")))
        tmp.replace(p)

    def migrate_json_file(self, legacy_path: Path, secure_path: Path, *, default_obj: Any) -> bool:
        legacy = Path(legacy_path)
        secure = Path(secure_path)
        self.cleanup_backups(legacy.parent, ttl_seconds=24 * 3600)

        if secure.exists():
            if legacy.exists():
                self._backup_then_remove(legacy)
            return False
        if not legacy.exists():
            return False

        try:
            raw = legacy.read_text(encoding="utf-8", errors="replace").strip()
            if not raw:
                obj = default_obj
            else:
                obj = json.loads(raw)
                if obj is None:
                    obj = default_obj
        except Exception as exc:
            raise LocalCryptoError(f"Could not parse legacy JSON file: {legacy}") from exc

        self.write_json(secure, obj)
        self._backup_then_remove(legacy)
        return True

    def migrate_binary_file(self, legacy_path: Path, secure_path: Path) -> bool:
        legacy = Path(legacy_path)
        secure = Path(secure_path)
        self.cleanup_backups(legacy.parent, ttl_seconds=24 * 3600)

        if secure.exists():
            if legacy.exists():
                self._backup_then_remove(legacy)
            return False
        if not legacy.exists():
            return False

        self.write_bytes(secure, legacy.read_bytes())
        self._backup_then_remove(legacy)
        return True

    def cleanup_backups(self, folder: Path, *, ttl_seconds: int = 24 * 3600) -> int:
        base = Path(folder)
        if not base.exists():
            return 0
        removed = 0
        now = time.time()
        for f in base.glob("*.bak.*"):
            try:
                age = now - float(f.stat().st_mtime)
                if age >= float(ttl_seconds):
                    f.unlink(missing_ok=True)
                    removed += 1
            except Exception:
                continue
        return removed

    def _aesgcm(self) -> "AESGCM":
        if AESGCM is None:
            raise LocalCryptoError("Missing dependency: cryptography")
        key = self._get_or_create_dek()
        if len(key) != 32:
            raise LocalCryptoError("Invalid local DEK length.")
        return AESGCM(key)

    def _get_or_create_dek(self) -> bytes:
        p = Path(self.key_path)
        if p.exists():
            raw = p.read_bytes()
            return self._unwrap_dek(raw)

        dek = os.urandom(32)
        wrapped = self._wrap_dek(dek)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(wrapped)
        tmp.replace(p)
        return dek

    def _wrap_dek(self, dek: bytes) -> bytes:
        if os.name == "nt" and protect_data is not None:
            try:
                return protect_data(dek, description="FALAI/local_dek")
            except Exception as exc:
                raise LocalCryptoError("Could not protect local DEK with DPAPI.") from exc
        # Non-Windows fallback for development/CI.
        return b"PLAINTEXT:" + base64.b64encode(dek)

    def _unwrap_dek(self, wrapped: bytes) -> bytes:
        raw = bytes(wrapped or b"")
        if os.name == "nt" and unprotect_data is not None:
            try:
                return unprotect_data(raw)
            except Exception as exc:
                raise LocalCryptoError("Could not unprotect local DEK with DPAPI.") from exc
        prefix = b"PLAINTEXT:"
        if raw.startswith(prefix):
            try:
                return base64.b64decode(raw[len(prefix) :], validate=True)
            except Exception as exc:
                raise LocalCryptoError("Invalid local DEK fallback format.") from exc
        raise LocalCryptoError("Invalid local DEK format.")

    def _backup_then_remove(self, legacy_path: Path) -> None:
        src = Path(legacy_path)
        if not src.exists():
            return
        stamp = int(time.time())
        bak = src.with_name(f"{src.name}.bak.{stamp}")
        try:
            bak.write_bytes(src.read_bytes())
        except Exception as exc:
            raise LocalCryptoError(f"Could not write migration backup for {src.name}") from exc
        try:
            src.unlink(missing_ok=True)
        except Exception as exc:
            raise LocalCryptoError(f"Could not remove legacy plaintext file {src.name}") from exc
