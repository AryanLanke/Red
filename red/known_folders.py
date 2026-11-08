"""Windows standard folders through the Known Folder API.

SHGetKnownFolderPath returns where a folder really is, so Downloads or
Documents still work after they were moved, for example to OneDrive.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# Folder name -> KNOWNFOLDERID (from KnownFolders.h).
FOLDER_IDS = {
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
}

# Other ways people say the same folder.
ALIASES = {
    "download": "downloads",
    "document": "documents",
    "docs": "documents",
    "picture": "pictures",
    "photos": "pictures",
    "video": "videos",
    "movies": "videos",
}


def normalize(name: str) -> str:
    """Lowercase a spoken or typed folder name and drop filler words.

    "My Documents folder" -> "documents".
    """
    words = name.strip().lower().replace("_", " ").split()
    while words and words[0] in {"my", "the"}:
        words = words[1:]
    while words and words[-1] in {"folder", "directory"}:
        words = words[:-1]
    return " ".join(words)


def canonical(name: str) -> str | None:
    """The FOLDER_IDS key for a name, or None if it isn't a known folder."""
    key = normalize(name)
    key = ALIASES.get(key, key)
    return key if key in FOLDER_IDS else None


def _shell_folder_path(folder_id: str) -> Path | None:
    """Call SHGetKnownFolderPath. Returns None if Windows has no such folder."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    u = uuid.UUID(folder_id)
    guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    shell32 = ctypes.WinDLL("shell32")
    ole32 = ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = (
        ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p))
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long  # HRESULT
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)

    out = ctypes.c_wchar_p()
    hr = shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(out))
    try:
        if hr != 0 or not out.value:
            return None
        return Path(out.value)
    finally:
        # The caller must free the buffer even when the call fails.
        ole32.CoTaskMemFree(out)


def known_folder(name: str) -> Path | None:
    """Where a standard folder ("downloads", "music", ...) is, or None."""
    key = canonical(name)
    if key is None:
        return None
    return _shell_folder_path(FOLDER_IDS[key])


def all_known_folders() -> dict[str, Path]:
    """Every standard folder Windows reports, by name."""
    found = {}
    for key, folder_id in FOLDER_IDS.items():
        path = _shell_folder_path(folder_id)
        if path is not None:
            found[key] = path
    return found
