"""Windows DPAPI helpers.

This module is Windows-first and intentionally tiny so other security modules
can reuse the same DPAPI implementation.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class DpapiError(RuntimeError):
    """Raised when DPAPI protect/unprotect fails."""


if sys.platform == "win32":
    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    _crypt32 = ctypes.WinDLL("Crypt32.dll")
    _kernel32 = ctypes.WinDLL("Kernel32.dll")

    _CryptProtectData = _crypt32.CryptProtectData
    _CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    _CryptProtectData.restype = wintypes.BOOL

    _CryptUnprotectData = _crypt32.CryptUnprotectData
    _CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    _CryptUnprotectData.restype = wintypes.BOOL

    _LocalFree = _kernel32.LocalFree
    _LocalFree.argtypes = [ctypes.c_void_p]
    _LocalFree.restype = ctypes.c_void_p


def _bytes_to_blob(data: bytes) -> tuple["DATA_BLOB", ctypes.Array[ctypes.c_char]]:
    raw = bytes(data or b"")
    if not raw:
        raw = b"\x00"
    buf = ctypes.create_string_buffer(raw, len(raw))
    blob = DATA_BLOB()
    blob.cbData = len(raw)
    blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
    return blob, buf


def protect_data(data: bytes, *, entropy: bytes | None = None, description: str = "FALAI") -> bytes:
    """Protect bytes with Windows DPAPI (CurrentUser)."""
    if sys.platform != "win32":
        raise DpapiError("DPAPI is available only on Windows.")

    in_blob, in_buf = _bytes_to_blob(data)
    entropy_blob = None
    entropy_buf = None
    if entropy:
        entropy_blob, entropy_buf = _bytes_to_blob(bytes(entropy))

    out_blob = DATA_BLOB()
    ok = _CryptProtectData(
        ctypes.byref(in_blob),
        description,
        ctypes.byref(entropy_blob) if entropy_blob is not None else None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise DpapiError(f"CryptProtectData failed: {ctypes.GetLastError()}")
    try:
        return bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    finally:
        if out_blob.pbData:
            _LocalFree(out_blob.pbData)


def unprotect_data(data: bytes, *, entropy: bytes | None = None) -> bytes:
    """Unprotect bytes with Windows DPAPI (CurrentUser)."""
    if sys.platform != "win32":
        raise DpapiError("DPAPI is available only on Windows.")

    in_blob, in_buf = _bytes_to_blob(data)
    entropy_blob = None
    entropy_buf = None
    if entropy:
        entropy_blob, entropy_buf = _bytes_to_blob(bytes(entropy))

    out_blob = DATA_BLOB()
    desc = wintypes.LPWSTR()
    ok = _CryptUnprotectData(
        ctypes.byref(in_blob),
        ctypes.byref(desc),
        ctypes.byref(entropy_blob) if entropy_blob is not None else None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise DpapiError(f"CryptUnprotectData failed: {ctypes.GetLastError()}")
    try:
        return bytes(ctypes.string_at(out_blob.pbData, out_blob.cbData))
    finally:
        if out_blob.pbData:
            _LocalFree(out_blob.pbData)
        if desc:
            _LocalFree(desc)
