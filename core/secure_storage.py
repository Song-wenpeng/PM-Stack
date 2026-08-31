# -*- coding: utf-8 -*-
"""Windows DPAPI helpers for storing user secrets without plaintext at rest."""

import base64
import ctypes
import os
from ctypes import wintypes


CRYPTPROTECT_UI_FORBIDDEN = 0x1


class SecretStorageError(RuntimeError):
    """Raised when a secret cannot be protected or restored."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _require_windows():
    if os.name != "nt":
        raise SecretStorageError("PM Stack 的安全密钥存储仅支持 Windows DPAPI")


def _input_blob(data):
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(
        len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    )
    return blob, buffer


def _release_blob(blob):
    if blob.pbData:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.c_void_p))


def protect_secret(value):
    """Encrypt a string for the current Windows user and return base64 text."""
    if not value:
        return ""
    _require_windows()

    raw = value.encode("utf-8")
    input_blob, input_buffer = _input_blob(raw)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        "PM Stack user secret",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    # Keep the input buffer alive until CryptProtectData returns.
    _ = input_buffer
    if not ok:
        raise SecretStorageError(str(ctypes.WinError()))

    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        _release_blob(output_blob)


def unprotect_secret(value):
    """Restore a base64 DPAPI payload for the current Windows user."""
    if not value:
        return ""
    _require_windows()

    try:
        encrypted = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise SecretStorageError("密钥存储内容不是有效的 base64 数据") from exc

    input_blob, input_buffer = _input_blob(encrypted)
    output_blob = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    _ = input_buffer
    if not ok:
        raise SecretStorageError(str(ctypes.WinError()))

    try:
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SecretStorageError("无法解码已保护的密钥") from exc
    finally:
        _release_blob(output_blob)
