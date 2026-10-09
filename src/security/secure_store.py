"""Secure session storage (Windows-first).

Windows implementation:
- Windows Credential Manager as storage backend.
- Values protected with DPAPI before being written to Credential Manager.
"""

from __future__ import annotations

import base64
import ctypes
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from src.utils.app_paths import ensure_app_data_dir
from src.utils.logger import get_logger

try:
    from src.security.win_dpapi import protect_data, unprotect_data
except Exception:  # pragma: no cover - fallback only
    protect_data = None
    unprotect_data = None


logger = get_logger(__name__)


SESSION_ACCESS_ID = "FALAI/session/access"
SESSION_REFRESH_ID = "FALAI/session/refresh"
SESSION_META_ID = "FALAI/session/meta"


class SecureStoreError(RuntimeError):
    """Raised when secure store operation fails."""


if sys.platform == "win32":
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
        _fields_ = [
            ("Keyword", wintypes.LPWSTR),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.POINTER(ctypes.c_byte)),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _advapi32 = ctypes.WinDLL("Advapi32.dll")

    _CredWriteW = _advapi32.CredWriteW
    _CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    _CredWriteW.restype = wintypes.BOOL

    _CredReadW = _advapi32.CredReadW
    _CredReadW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    _CredReadW.restype = wintypes.BOOL

    _CredDeleteW = _advapi32.CredDeleteW
    _CredDeleteW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDeleteW.restype = wintypes.BOOL

    _CredFree = _advapi32.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]
    _CredFree.restype = None


class SecureStore:
    """Secure storage for access/refresh session values."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._fallback_path = ensure_app_data_dir() / ".secure_store_fallback.json"

    def get_access_token(self) -> str:
        return self.get_secret(SESSION_ACCESS_ID)

    def get_refresh_token(self) -> str:
        return self.get_secret(SESSION_REFRESH_ID)

    def set_access_token(self, token: str) -> None:
        self.set_secret(SESSION_ACCESS_ID, token)

    def set_refresh_token(self, token: str) -> None:
        self.set_secret(SESSION_REFRESH_ID, token)

    def delete_access_token(self) -> None:
        self.delete_secret(SESSION_ACCESS_ID)

    def delete_refresh_token(self) -> None:
        self.delete_secret(SESSION_REFRESH_ID)

    def clear_session_tokens(self) -> None:
        self.delete_secret(SESSION_ACCESS_ID)
        self.delete_secret(SESSION_REFRESH_ID)
        self.delete_secret(SESSION_META_ID)

    def get_session_meta(self) -> dict[str, Any]:
        raw = self.get_secret(SESSION_META_ID)
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def set_session_meta(self, meta: dict[str, Any]) -> None:
        payload = dict(meta or {})
        payload.setdefault("updated_at", int(time.time()))
        self.set_secret(SESSION_META_ID, json.dumps(payload, ensure_ascii=True, separators=(",", ":")))

    def set_secret(self, target: str, value: str) -> None:
        with self._lock:
            v = str(value or "")
            if not v:
                self.delete_secret(target)
                return
            data = v.encode("utf-8")
            if sys.platform == "win32":
                self._set_secret_windows(target, data)
                return
            self._set_secret_fallback(target, data)

    def get_secret(self, target: str) -> str:
        with self._lock:
            if sys.platform == "win32":
                raw = self._get_secret_windows(target)
            else:
                raw = self._get_secret_fallback(target)
            if not raw:
                return ""
            try:
                return raw.decode("utf-8", errors="strict")
            except Exception:
                return ""

    def delete_secret(self, target: str) -> None:
        with self._lock:
            if sys.platform == "win32":
                self._delete_secret_windows(target)
                return
            self._delete_secret_fallback(target)

    # ------------------------------
    # Windows backend
    # ------------------------------
    def _set_secret_windows(self, target: str, data: bytes) -> None:
        if protect_data is None:
            raise SecureStoreError("DPAPI backend not available on this runtime.")
        try:
            protected = protect_data(data, description=f"FALAI:{target}")
        except Exception as exc:
            raise SecureStoreError(f"DPAPI protect failed for '{target}'.") from exc

        blob_buf = ctypes.create_string_buffer(protected, len(protected))
        cred = CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = ctypes.c_wchar_p(str(target))
        cred.CredentialBlobSize = len(protected)
        cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = None

        ok = _CredWriteW(ctypes.byref(cred), 0)
        if not ok:
            raise SecureStoreError(f"Credential write failed for '{target}' (winerr={ctypes.GetLastError()}).")

    def _get_secret_windows(self, target: str) -> bytes:
        cred_ptr = ctypes.POINTER(CREDENTIALW)()
        ok = _CredReadW(str(target), CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
        if not ok:
            return b""
        try:
            cred = cred_ptr.contents
            if not cred.CredentialBlob or int(cred.CredentialBlobSize or 0) <= 0:
                return b""
            protected = bytes(ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize))
        finally:
            _CredFree(cred_ptr)

        if unprotect_data is None:
            raise SecureStoreError("DPAPI backend not available on this runtime.")
        try:
            return unprotect_data(protected)
        except Exception as exc:
            # Corrupt/revoked credential should force a clean login path.
            raise SecureStoreError(f"Credential decrypt failed for '{target}'.") from exc

    def _delete_secret_windows(self, target: str) -> None:
        # Best-effort delete; absence is acceptable.
        try:
            _CredDeleteW(str(target), CRED_TYPE_GENERIC, 0)
        except Exception:
            return

    # ------------------------------
    # Fallback backend (non-Windows)
    # ------------------------------
    def _read_fallback(self) -> dict[str, str]:
        p = Path(self._fallback_path)
        if not p.exists():
            return {}
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return {str(k): str(v) for k, v in obj.items()}
        except Exception:
            return {}
        return {}

    def _write_fallback(self, obj: dict[str, str]) -> None:
        p = Path(self._fallback_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=True, indent=2), encoding="utf-8")
        tmp.replace(p)

    def _set_secret_fallback(self, target: str, data: bytes) -> None:
        obj = self._read_fallback()
        obj[str(target)] = base64.b64encode(data).decode("ascii")
        self._write_fallback(obj)

    def _get_secret_fallback(self, target: str) -> bytes:
        obj = self._read_fallback()
        raw = obj.get(str(target), "")
        if not raw:
            return b""
        try:
            return base64.b64decode(raw.encode("ascii"), validate=True)
        except Exception:
            return b""

    def _delete_secret_fallback(self, target: str) -> None:
        obj = self._read_fallback()
        if str(target) not in obj:
            return
        obj.pop(str(target), None)
        self._write_fallback(obj)


_STORE_SINGLETON: Optional[SecureStore] = None
_STORE_LOCK = threading.Lock()


def get_secure_store() -> SecureStore:
    global _STORE_SINGLETON
    if _STORE_SINGLETON is not None:
        return _STORE_SINGLETON
    with _STORE_LOCK:
        if _STORE_SINGLETON is None:
            _STORE_SINGLETON = SecureStore()
    return _STORE_SINGLETON
