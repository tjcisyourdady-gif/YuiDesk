"""API Key 本地安全加密（Windows 下使用 DPAPI CryptProtectData）."""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import os


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def encrypt_secret(plaintext: str) -> str:
    """将敏感字符串加密为带前缀的 Base64 文本."""
    if not plaintext:
        return ""
    raw = plaintext.encode("utf-8")
    if os.name == "nt":
        try:
            crypt32 = ctypes.windll.crypt32
            kernel32 = ctypes.windll.kernel32
            in_buf = ctypes.create_string_buffer(raw, len(raw))
            in_blob = _DataBlob(len(raw), in_buf)
            out_blob = _DataBlob()
            if crypt32.CryptProtectData(
                ctypes.byref(in_blob),
                "YuiDeskSecret",
                None,
                None,
                None,
                0x01,  # CRYPTPROTECT_UI_FORBIDDEN
                ctypes.byref(out_blob),
            ):
                try:
                    encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                    return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
                finally:
                    kernel32.LocalFree(out_blob.pbData)
        except Exception:
            pass
    # 非 Windows 或异常时的轻量混淆降级
    return "b64:" + base64.b64encode(raw).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """解密存储的敏感字符串."""
    if not ciphertext:
        return ""
    if ciphertext.startswith("dpapi:") and os.name == "nt":
        try:
            raw = base64.b64decode(ciphertext[6:])
            crypt32 = ctypes.windll.crypt32
            kernel32 = ctypes.windll.kernel32
            in_buf = ctypes.create_string_buffer(raw, len(raw))
            in_blob = _DataBlob(len(raw), in_buf)
            out_blob = _DataBlob()
            if crypt32.CryptUnprotectData(
                ctypes.byref(in_blob),
                None,
                None,
                None,
                None,
                0x01,
                ctypes.byref(out_blob),
            ):
                try:
                    decrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
                    return decrypted.decode("utf-8")
                finally:
                    kernel32.LocalFree(out_blob.pbData)
        except Exception:
            return ""
    if ciphertext.startswith("b64:"):
        try:
            return base64.b64decode(ciphertext[4:]).decode("utf-8")
        except Exception:
            return ""
    # 兼容明文历史值
    return ciphertext


def mask_secret(secret: str) -> str:
    """用于前端展示的脱敏掩码."""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * min(12, len(secret) - 8)}{secret[-4:]}"
