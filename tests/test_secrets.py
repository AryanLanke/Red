"""red.secrets: DPAPI round trips (a real, silent Windows call; no prompt, no network)."""

import pytest

from red import secrets


def test_round_trip(tmp_path):
    path = secrets.save(tmp_path, "spotify", {"refresh_token": "abc123", "scope": "x"})
    assert path == tmp_path / "config" / "secrets" / "spotify.bin"
    assert b"abc123" not in path.read_bytes()                  # never plain text on disk
    assert secrets.load(tmp_path, "spotify") == {"refresh_token": "abc123", "scope": "x"}
    assert secrets.exists(tmp_path, "spotify")
    assert secrets.delete(tmp_path, "spotify") and secrets.load(tmp_path, "spotify") is None
    assert not secrets.delete(tmp_path, "spotify")


def test_a_tampered_file_doesnt_decrypt(tmp_path):
    path = secrets.save(tmp_path, "mail", "app-password")
    data = bytearray(path.read_bytes())
    data[-5] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(secrets.SecretError):
        secrets.load(tmp_path, "mail")


def test_names_are_plain(tmp_path):
    for bad in ("../x", "a\\b", "", "UPPER"):
        with pytest.raises(secrets.SecretError):
            secrets.save(tmp_path, bad, "x")


def test_secrets_folder_is_ignored_by_git():
    from pathlib import Path
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "secrets/" in ignore
