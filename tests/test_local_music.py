"""play_local: only audio files under the Music folder, opened with the default player, never a model's path."""

import random
from pathlib import Path

import pytest

from red.tools.base import ToolError
from red.tools.local_music import PlayLocal, inside, match, scan, title_of


@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Music"
    for rel in ["Daft Punk/01 - Get Lucky.mp3", "Daft Punk/02 - Around the World.mp3",
                "Queen/Bohemian Rhapsody.flac", "loose song.wav", "notes.txt", "Queen/cover.jpg",
                ".hidden/secret.mp3"]:
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    return root


class Opened:
    def __init__(self):
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)


def tool(music, opened=None):
    return PlayLocal(root=music, startfile=opened or Opened(), rng=random.Random(1))


def test_scan_finds_audio_only_and_skips_hidden_folders(music):
    names = sorted(p.name for p in scan(music))
    assert names == ["01 - Get Lucky.mp3", "02 - Around the World.mp3", "Bohemian Rhapsody.flac", "loose song.wav"]
    assert scan(None) == [] and scan(music / "nope") == []


def test_scan_stops_at_the_limit(music):
    assert len(scan(music, limit=2)) == 2


def test_titles_are_fit_to_say_aloud():
    assert title_of(Path("01 - Daft Punk - Get Lucky.mp3")) == "Daft Punk - Get Lucky"
    assert title_of(Path("my_song_name.mp3")) == "my song name"


def test_match_uses_file_and_folder_names(music):
    files = scan(music)
    assert [p.name for p in match(files, music, "daft punk")] == ["01 - Get Lucky.mp3", "02 - Around the World.mp3"]
    assert [p.name for p in match(files, music, "play queen")] == ["Bohemian Rhapsody.flac"]
    assert [p.name for p in match(files, music, "get lucky")] == ["01 - Get Lucky.mp3"]
    assert match(files, music, "taylor swift") == []
    assert len(match(files, music, "play some music")) == len(files), "filler words alone mean any song"


def test_run_plays_a_matching_file_with_the_default_player(music):
    opened = Opened()
    reply = tool(music, opened).run("bohemian rhapsody")
    assert reply == "Playing Bohemian Rhapsody."
    assert [Path(p).name for p in opened.paths] == ["Bohemian Rhapsody.flac"]


def test_run_with_no_query_plays_something(music):
    opened = Opened()
    assert tool(music, opened).run("").startswith("Playing ") and len(opened.paths) == 1


def test_a_path_in_the_query_is_only_words_never_opened(music, tmp_path):
    outside = tmp_path / "evil.mp3"
    outside.write_bytes(b"x")
    opened = Opened()
    with pytest.raises(ToolError):
        tool(music, opened).run(str(outside))
    with pytest.raises(ToolError):
        tool(music, opened).run(r"..\..\evil.mp3 C:\Windows\System32\cmd.exe")
    assert opened.paths == []


def test_play_refuses_anything_outside_the_folder_or_not_audio(music, tmp_path):
    opened = Opened()
    t = tool(music, opened)
    outside = tmp_path / "evil.mp3"
    outside.write_bytes(b"x")
    for bad in (outside, music / "notes.txt", music / ".." / "evil.mp3", music / "missing.mp3"):
        with pytest.raises(ToolError):
            t.play(bad)
    assert opened.paths == []


def test_inside_resolves_dots_and_rejects_siblings(music, tmp_path):
    assert inside(music, music / "Queen" / "Bohemian Rhapsody.flac")
    assert not inside(music, music / "Queen" / ".." / ".." / "evil.mp3")
    sibling = tmp_path / "Music2"
    sibling.mkdir()
    (sibling / "a.mp3").write_bytes(b"x")
    assert not inside(music, sibling / "a.mp3"), "a folder whose name starts the same is not inside"


def test_a_link_out_of_the_folder_is_not_followed(music, tmp_path):
    secret = tmp_path / "private"
    secret.mkdir()
    (secret / "diary.mp3").write_bytes(b"x")
    try:
        (music / "link").symlink_to(secret, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("no permission to make symbolic links here")
    assert "diary.mp3" not in {p.name for p in scan(music)}
    opened = Opened()
    with pytest.raises(ToolError):
        tool(music, opened).play(music / "link" / "diary.mp3")
    assert opened.paths == []


def test_empty_or_missing_folder_says_so(tmp_path):
    (tmp_path / "Music").mkdir()
    with pytest.raises(ToolError, match="no music"):
        tool(tmp_path / "Music").run("")
    with pytest.raises(ToolError, match="Music folder"):
        PlayLocal(root=tmp_path / "nowhere", startfile=Opened()).run("x")


def test_pick_avoids_recent_songs_when_it_can(music):
    t = tool(music)
    files = scan(music)
    recent = set(files[:3])
    for _ in range(10):
        assert t.pick("", avoid=recent) == files[3]
    assert t.pick("daft punk", avoid=set(files)) is not None, "better a repeat than silence"


def test_the_real_registry_does_not_carry_it():
    from red.tools import default_registry
    assert "play_local" not in default_registry(google=False, plugins=False)


def test_a_junction_out_of_the_folder_is_not_followed(music, tmp_path):
    import subprocess
    import sys
    if sys.platform != "win32":
        pytest.skip("junctions are Windows only")
    secret = tmp_path / "private2"
    secret.mkdir()
    (secret / "diary.mp3").write_bytes(b"x")
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(music / "jn"), str(secret)],
                          capture_output=True, text=True)
    if made.returncode != 0:
        pytest.skip("couldn't make a junction")
    assert "diary.mp3" not in {p.name for p in scan(music)}
    opened = Opened()
    with pytest.raises(ToolError):
        tool(music, opened).play(music / "jn" / "diary.mp3")
    assert opened.paths == []
