"""API Key 的本地加密存储。

Windows 上用 DPAPI（CryptProtectData）加密——系统级、零额外依赖，
密文只有**同一台机器、同一个 Windows 用户**能解开。
非 Windows 或调用失败时降级为明文，并打上 "plain:" 前缀以区分。
"""
from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

DPAPI_PREFIX = "dpapi:"
PLAIN_PREFIX = "plain:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


_crypt32 = None
_kernel32 = None
if sys.platform == "win32":
    try:
        _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        _crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
        _crypt32.CryptProtectData.restype = wintypes.BOOL

        _crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
        _crypt32.CryptUnprotectData.restype = wintypes.BOOL

        _kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        _kernel32.LocalFree.restype = wintypes.HLOCAL
    except Exception:            # pragma: no cover
        _crypt32 = _kernel32 = None


def _blob(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    return blob, buf


def _dpapi_available() -> bool:
    return _crypt32 is not None and _kernel32 is not None


def encrypt(plain: str) -> str:
    """明文 -> 可入库的字符串。"""
    if not plain:
        return ""
    if not _dpapi_available():
        return PLAIN_PREFIX + plain
    try:
        data = plain.encode("utf-8")
        blob_in, _buf = _blob(data)
        blob_out = _DATA_BLOB()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            return PLAIN_PREFIX + plain
        try:
            raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)
        return DPAPI_PREFIX + base64.b64encode(raw).decode("ascii")
    except Exception:
        return PLAIN_PREFIX + plain


def decrypt(stored: str) -> str:
    """入库字符串 -> 明文。"""
    if not stored:
        return ""
    if stored.startswith(PLAIN_PREFIX):
        return stored[len(PLAIN_PREFIX):]
    if not stored.startswith(DPAPI_PREFIX):
        return stored                                  # 老数据：本来就是明文
    if not _dpapi_available():
        return ""
    try:
        raw = base64.b64decode(stored[len(DPAPI_PREFIX):])
        blob_in, _buf = _blob(raw)
        blob_out = _DATA_BLOB()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
        if not ok:
            return ""
        try:
            clear = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)
        return clear.decode("utf-8", "ignore")
    except Exception:
        return ""


def mask(value: str, head: int = 6, tail: int = 4) -> str:
    """sk-8aea…d5fc"""
    if not value:
        return "（未设置）"
    if len(value) <= head + tail:
        return value[:2] + "…"
    return f"{value[:head]}…{value[-tail:]}"
