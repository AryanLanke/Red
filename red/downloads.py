"""Checksum-verified downloads and safe zip extraction."""

from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

USER_AGENT = "red-assistant/0.1"
CHUNK = 1024 * 1024


class DownloadError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path, sha256: str, label: str | None = None) -> Path:
    """Download url to dest, resuming a partial download, and verify sha256.

    The file only appears at dest once its checksum matches, so an existing
    dest is always a verified file.
    """
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    label = label or dest.name

    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have:
        req.add_header("Range", f"bytes={have}-")

    try:
        resp = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:  # .part is already complete
            resp = None
        else:
            raise DownloadError(f"{label}: HTTP {e.code} from {url}") from e
    except urllib.error.URLError as e:
        raise DownloadError(f"{label}: cannot reach {url} ({e.reason})") from e

    if resp is not None:
        with resp:
            resumed = have and getattr(resp, "status", 200) == 206
            if not resumed:
                have = 0
            length = resp.headers.get("Content-Length")
            total = have + int(length) if length else None
            done, last_pct = have, -1
            with part.open("ab" if resumed else "wb") as f:
                for block in iter(lambda: resp.read(CHUNK), b""):
                    f.write(block)
                    done += len(block)
                    if total:
                        pct = done * 100 // total
                        if pct != last_pct:
                            last_pct = pct
                            print(f"\r  {label}: {pct}% of {total / 1e9:.2f} GB",
                                  end="", file=sys.stderr, flush=True)
            print(file=sys.stderr)

    actual = sha256_file(part)
    if actual != sha256.lower():
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"{label}: checksum mismatch (expected {sha256}, got {actual}). "
            "The partial file was deleted; run setup again."
        )
    part.replace(dest)
    return dest


def safe_extract(zip_path: Path, target: Path) -> None:
    """Extract a zip, refusing entries that would land outside target."""
    target = target.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            out = (target / member.filename).resolve()
            if not out.is_relative_to(target):
                raise DownloadError(f"{zip_path.name}: unsafe path {member.filename!r}")
        zf.extractall(target)
