"""find_file and open_found_file on a temporary folder tree. Nothing is opened."""

import os
import time
from pathlib import Path

import pytest

from red.allowlist import Allowlist
from red.tools.base import ToolError
from red.tools.files import (FindFile, FoundFiles, OpenFoundFile, default_roots, query_words,
                             score, search)


@pytest.fixture
def tree(tmp_path):
    files = {
        "Documents/Jobs/Resume_2024.pdf": 100,     # hours old
        "Documents/Jobs/Old Resume.docx": 300,
        "Documents/Budget 2025.xlsx": 200,
        "Documents/notes.txt": 50,
        "Documents/node_modules/resume.js": 999,     # skipped folder
        "Documents/.hidden/resume.pdf": 999,         # hidden folder
        "Downloads/setup_resume_builder.exe": 400,
        "Downloads/tax-return.pdf": 10,
        "Desktop/Projects/Red/readme.md": 20,
        "Desktop/Holiday Photos/beach.jpg": 30,
    }
    for rel, age in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        t = time.time() - age * 3600
        os.utime(p, (t, t))
    return tmp_path


def roots(tree):
    return [("Desktop", tree / "Desktop"), ("Documents", tree / "Documents"),
            ("Downloads", tree / "Downloads")]


def names(result):
    return [m.path.name for m in result.matches]


def test_finds_and_ranks(tree):
    r = search("resume", roots(tree))
    # whole-word matches first, newest first; the .exe only contains the word
    assert names(r) == ["Resume_2024.pdf", "Old Resume.docx", "setup_resume_builder.exe"]
    assert not r.partial


def test_exact_name_wins(tree):
    assert names(search("old resume", roots(tree)))[0] == "Old Resume.docx"


def test_skips_tool_and_hidden_folders(tree):
    found = [str(m.path) for m in search("resume", roots(tree)).matches]
    assert not any("node_modules" in p or ".hidden" in p for p in found)


@pytest.mark.parametrize("query, first", [
    ("budget spreadsheet 2025", None),     # "spreadsheet" isn't in the name
    ("budget", "Budget 2025.xlsx"),
    ("the budget 2025 file", "Budget 2025.xlsx"),
    ("tax return", "tax-return.pdf"),
    ("holiday photos", "Holiday Photos"),
    ("buget", "Budget 2025.xlsx"),          # misheard
    ("readme", "readme.md"),
])
def test_queries(tree, query, first):
    got = names(search(query, roots(tree)))
    assert (got[0] if got else None) == first


def test_kind_filter(tree):
    assert names(search("photos", roots(tree), kind="folder")) == ["Holiday Photos"]
    assert names(search("photos", roots(tree), kind="file")) == []


def test_result_cap(tree):
    for i in range(10):
        (tree / "Documents" / f"report {i}.txt").write_text("x")
    assert len(search("report", roots(tree), max_results=5).matches) == 5


def test_time_limit_stops_the_search(tree):
    ticks = iter(range(1000))
    r = search("resume", roots(tree), time_limit=3, clock=lambda: next(ticks))
    assert r.partial and r.looked_at <= 5


def test_entry_limit_stops_the_search(tree):
    r = search("beach", roots(tree), max_entries=3)
    assert r.partial and r.matches == []


def test_search_is_read_only(tree):
    def snapshot():
        return sorted((str(p), p.stat().st_mtime) for p in tree.rglob("*"))
    before = snapshot()
    search("resume", roots(tree))
    assert snapshot() == before


def test_unreadable_folder_is_skipped(tree):
    def scandir(path):
        if Path(path).name == "Jobs":
            raise PermissionError("denied")
        return os.scandir(path)
    assert names(search("resume", roots(tree), scandir=scandir)) == ["setup_resume_builder.exe"]


def test_query_words_and_score():
    assert query_words("my Resume file") == ["resume"]
    assert score("Resume_2024.pdf", ["resume"]) == 3
    assert score("resume.pdf", ["resume"]) == 4
    assert score("myresume.pdf", ["resume"]) == 2
    assert score("resme.pdf", ["resume"]) == 1
    assert score("cv.pdf", ["resume"]) == 0


# --- the tools -------------------------------------------------------------------

class FakeStart:
    def __init__(self):
        self.calls = []

    def __call__(self, path):
        self.calls.append(path)


def tools(tree):
    found = FoundFiles()
    start = FakeStart()
    return (FindFile(roots=lambda: roots(tree), found=found),
            OpenFoundFile(found=found, startfile=start), start)


def test_find_then_open(tree):
    find, open_, start = tools(tree)
    reply = find.run(name="resume")
    assert reply == ("I found Resume_2024.pdf in Documents\\Jobs, and 2 other matches. "
                     "Say open it to open it.")
    assert find.last_details.splitlines()[0].startswith("1. Resume_2024.pdf (file) in Documents")
    assert open_.run() == "Opening Resume_2024.pdf."
    assert open_.run(number=2) == "Opening Old Resume.docx."
    assert start.calls == [str(tree / "Documents/Jobs/Resume_2024.pdf"),
                           str(tree / "Documents/Jobs/Old Resume.docx")]


def test_programs_are_never_run(tree):
    find, open_, start = tools(tree)
    find.run(name="resume builder")
    reply = open_.run()
    assert reply == "setup_resume_builder.exe is a program or script, so I opened its folder instead."
    assert start.calls == [str(tree / "Downloads")]


def test_folder_result(tree):
    find, open_, start = tools(tree)
    assert find.run(name="holiday photos").startswith(
        "I found a folder called Holiday Photos in Desktop.")
    open_.run()
    assert start.calls == [str(tree / "Desktop/Holiday Photos")]


def test_nothing_found(tree):
    find, open_, _ = tools(tree)
    assert find.run(name="passport scan") == \
        "I couldn't find anything called passport scan in your folders."
    with pytest.raises(ToolError, match="Find a file first"):
        open_.run()


def test_open_errors(tree):
    find, open_, _ = tools(tree)
    with pytest.raises(ToolError, match="Find a file first"):
        open_.run()
    find.run(name="notes")
    with pytest.raises(ToolError, match="I only found 1 match"):
        open_.run(number=3)
    (tree / "Documents/notes.txt").unlink()
    with pytest.raises(ToolError, match="isn't there any more"):
        open_.run()


def test_empty_query(tree):
    find, _, _ = tools(tree)
    with pytest.raises(ToolError):
        find.run(name="my file")


def test_default_roots_use_known_folders_then_allowlist(tree):
    allow = Allowlist(folders={"projects": tree / "Desktop/Projects",
                               "gone": tree / "nope"})
    known = {"documents": tree / "Documents", "desktop": tree / "Desktop"}
    got = default_roots(allowlist=allow, known=lambda: known)
    assert got == [("Desktop", tree / "Desktop"), ("Documents", tree / "Documents"),
                   ("projects", tree / "Desktop/Projects")]


def test_broken_allowlist_still_searches_known_folders(tree):
    def broken():
        raise ToolError("bad toml")
    got = default_roots(allowlist=broken, known=lambda: {"documents": tree / "Documents"})
    assert got == [("Documents", tree / "Documents")]


def test_nested_roots_are_not_searched_twice(tree):
    r = search("readme", [("Desktop", tree / "Desktop"), ("red", tree / "Desktop/Projects/Red")])
    assert names(r) == ["readme.md"]
