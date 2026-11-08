import sys
from pathlib import Path

import pytest

from red import known_folders
from red.allowlist import (DEFAULT_APPS, Allowlist, AllowlistError, load_allowlist,
                           parse_allowlist)

EXAMPLE = Path(__file__).resolve().parent.parent / "allowlist.example.toml"


@pytest.mark.parametrize("name, key", [
    ("Downloads", "downloads"),
    ("download", "downloads"),
    ("My Documents folder", "documents"),
    ("the desktop", "desktop"),
    ("photos", "pictures"),
    ("MUSIC", "music"),
    ("videos directory", "videos"),
    ("projects", None),
    ("C:\\Windows", None),
])
def test_canonical_names(name, key):
    assert known_folders.canonical(name) == key


@pytest.mark.skipif(sys.platform != "win32", reason="Known Folder API is Windows only")
def test_known_folder_api_returns_real_folders():
    # Read-only call into shell32; nothing is opened.
    downloads = known_folders.known_folder("downloads")
    assert downloads is not None and downloads.is_absolute() and downloads.is_dir()
    assert known_folders.known_folder("not a folder") is None
    assert set(known_folders.all_known_folders()) == set(known_folders.FOLDER_IDS)


def test_missing_file_gives_defaults(tmp_path):
    allow = load_allowlist(tmp_path / "nope.toml")
    assert allow == Allowlist()
    assert allow.app("Notepad") == DEFAULT_APPS["notepad"]
    assert allow.app("the calculator app") == ("calc.exe",)
    assert allow.app("Task Manager") == ("taskmgr.exe",)
    assert allow.app("File Explorer") == ("explorer.exe",)
    assert allow.app("vs code") is None
    assert allow.folder("projects") is None


def test_parse_folders_and_apps(monkeypatch):
    monkeypatch.setenv("TESTAPPDIR", "D:\\Apps")
    allow = parse_allowlist(r'''
[folders]
Projects = 'D:\Projects'
"Big Games" = 'E:\Games'

[apps]
"VS Code" = "code"
editor = '%TESTAPPDIR%\editor.exe'
notes = ['notepad.exe', 'D:\notes.txt']
notepad = 'C:\Tools\notepad2.exe'
''')
    assert allow.folder("projects") == Path("D:/Projects")
    assert allow.folder("my projects folder") == Path("D:/Projects")
    assert allow.folder("big games") == Path("E:/Games")
    assert allow.app("vs code") == ("code",)
    assert allow.app("Editor") == ("D:\\Apps\\editor.exe",)
    assert allow.app("notes") == ("notepad.exe", "D:\\notes.txt")
    assert allow.app("notepad") == ("C:\\Tools\\notepad2.exe",)  # user entry wins
    assert "calculator" in allow.app_names() and "vs code" in allow.app_names()


@pytest.mark.parametrize("text", [
    "[folders\n",                        # syntax error
    "folders = 1",                       # not a table
    "[folders]\nx = 5",                  # not a string
    "[folders]\nx = 'relative\\path'",   # not a full path
    "[apps]\nx = 5",
    "[apps]\nx = []",
    "[apps]\nx = ['']",
    "[apps]\nx = ['a', 1]",
])
def test_bad_allowlist_rejected(text):
    with pytest.raises(AllowlistError):
        parse_allowlist(text)


def test_example_file_parses():
    allow = parse_allowlist(EXAMPLE.read_text(encoding="utf-8"))
    assert allow.folder("projects") == Path("D:/Projects")
    assert allow.app("vs code")[0].endswith("Code.exe")
