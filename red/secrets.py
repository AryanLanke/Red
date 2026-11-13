"""Sign-in tokens and app passwords, encrypted for this Windows user (plan.md B3).

Windows DPAPI (`CryptProtectData` in crypt32, a signed system API, through
ctypes) encrypts each secret so only this user on this PC can read it back.
Secrets live in RED_HOME\\config\\secrets\\<name>.bin, never in git and never
in plain text. Red only stores what a plugin's sign-in needs (a Spotify refresh
token, a mail app password) and sends each one only to its own service.
"""

from __future__ import annotations

import ctypes
import json
import re
import sys
from ctypes import wintypes
from pathlib import Path

NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,60}$")
ENTROPY = b"Red companion secret v1"          # ties the blob to Red, on top of the user key


class SecretError(RuntimeError):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _call(func_name: str, data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretError("Encrypted secrets need Windows (DPAPI).")
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    data_in, keep_in = _blob(data)
    entropy, keep_entropy = _blob(ENTROPY)
    out = _Blob()
    func = getattr(crypt32, func_name)
    # CRYPTPROTECT_UI_FORBIDDEN (0x1): never show a prompt.
    args = ((ctypes.byref(data_in), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out))
            if func_name == "CryptUnprotectData" else
            (ctypes.byref(data_in), "Red", ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out)))
    if not func(*args):
        raise SecretError(f"Windows couldn't {'decrypt' if 'Un' in func_name else 'encrypt'} "
                          f"the secret (error {ctypes.GetLastError()}).")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> bytes:
    return _call("CryptProtectData", data)


def unprotect(blob: bytes) -> bytes:
    return _call("CryptUnprotectData", blob)


def secrets_dir(home: Path) -> Path:
    return Path(home) / "config" / "secrets"


def _path(home: Path, name: str) -> Path:
    if not NAME.match(name):
        raise SecretError(f"Bad secret name {name!r}")
    return secrets_dir(home) / f"{name}.bin"


def save(home: Path, name: str, value: dict | str) -> Path:
    """Encrypt and store a secret (a string or a JSON-able dict)."""
    path = _path(home, name)
    blob = protect(json.dumps(value).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)
    return path


def load(home: Path, name: str):
    """The stored value, or None when there isn't one."""
    path = _path(home, name)
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return None
    return json.loads(unprotect(blob).decode("utf-8"))


def delete(home: Path, name: str) -> bool:
    path = _path(home, name)
    if path.exists():
        path.unlink()
        return True
    return False


def exists(home: Path, name: str) -> bool:
    return _path(home, name).is_file()
