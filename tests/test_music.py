"""Music tool tests. No sound is ever played: tools get a fake player, and the
real pygame test uses SDL's silent "dummy" audio driver."""

import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from red.tools import music
from red.tools.music import (Library, NextSong, PauseMusic, PlayMusic, PygamePlayer,
                             ResumeMusic, StopMusic, music_dir, song_title)

SONGS = [
    "Daft Punk/Random Access Memories/08 - Get Lucky.mp3",
    "Daft Punk/Discovery/01 One More Time.flac",
    "Daft Punk/Discovery/03. Digital Love.mp3",
    "The Beatles/Abbey Road/07 - Here Comes the Sun.ogg",
    "The Beatles/Help!/Yesterday.mp3",
    "Jazz/Miles Davis - So What.wav",
    "Jazz/Take Five.opus",
    "Beyoncé/Halo.mp3",
    "loose song.MP3",
    "cover.jpg",
    "notes.txt",
    ".hidden/secret.mp3",
]


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Music"
    for rel in SONGS:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    return Library(root)


def names(paths):
    return sorted(p.name for p in paths)


class FakePlayer:
    def __init__(self, fail=None):
        self.queue, self.index, self._paused, self.fail = [], -1, False, fail

    @property
    def current(self):
        return self.queue[self.index] if 0 <= self.index < len(self.queue) else None

    @property
    def paused(self):
        return self._paused

    def play(self, tracks):
        if self.fail:
            raise music.PlayerError(self.fail)
        self.queue, self.index, self._paused = list(tracks), 0, False
        return self.current

    def stop(self):
        was = bool(self.queue)
        self.queue, self.index = [], -1
        return was

    def pause(self):
        if not self.queue or self._paused:
            return False
        self._paused = True
        return True

    def resume(self):
        if not self.queue or not self._paused:
            return False
        self._paused = False
        return True

    def next(self):
        if self.index + 1 < len(self.queue):
            self.index += 1
            return self.current
        self.stop()
        return None


def no_shuffle(items):
    pass


# --- library ---------------------------------------------------------------

def test_scan_finds_supported_files_and_skips_hidden(library):
    found = library.scan()
    assert len(found) == 9
    assert "cover.jpg" not in names(found) and "secret.mp3" not in names(found)
    assert "loose song.MP3" in names(found)     # extension check ignores case


def test_scan_stops_at_limit(library):
    assert len(Library(library.root, max_files=3).scan()) == 3


@pytest.mark.parametrize("query, expected", [
    ("Get Lucky", ["08 - Get Lucky.mp3"]),
    ("get lucky by daft punk", ["08 - Get Lucky.mp3"]),
    ("yesterday", ["Yesterday.mp3"]),
    ("here comes the sun", ["07 - Here Comes the Sun.ogg"]),
    ("discovery", ["01 One More Time.flac", "03. Digital Love.mp3"]),
    ("the beatles", ["07 - Here Comes the Sun.ogg", "Yesterday.mp3"]),
    ("beatles", ["07 - Here Comes the Sun.ogg", "Yesterday.mp3"]),
    ("songs by daft punk", ["01 One More Time.flac", "03. Digital Love.mp3",
                            "08 - Get Lucky.mp3"]),
    ("jazz", ["Miles Davis - So What.wav", "Take Five.opus"]),
    ("miles davis", ["Miles Davis - So What.wav"]),
    ("beyonce", ["Halo.mp3"]),                    # accents ignored
    ("dafft punk", ["01 One More Time.flac", "03. Digital Love.mp3",
                    "08 - Get Lucky.mp3"]),       # misheard
    ("take 5", []),
    ("metallica", []),
])
def test_find(library, query, expected):
    assert names(library.find(query)) == expected


def test_exact_title_beats_partial_matches(library):
    # "one more time" is a title; it shouldn't also return songs that only share words.
    assert names(library.find("one more time")) == ["01 One More Time.flac"]


def test_filler_only_query_matches_nothing(library):
    assert library.find("some music") == []


@pytest.mark.parametrize("stem, title", [
    ("08 - Get Lucky", "Get Lucky"), ("03. Digital Love", "Digital Love"),
    ("01 One More Time", "One More Time"), ("Yesterday", "Yesterday"),
    ("1999", "1999"), ("7 Rings", "7 Rings"), ("3. Song", "Song"),
])
def test_song_title(stem, title):
    assert song_title(Path(stem + ".mp3")) == title


def test_music_dir_default_and_override(monkeypatch, tmp_path):
    monkeypatch.delenv("RED_MUSIC_DIR", raising=False)
    assert music_dir() == Path.home() / "Music"
    monkeypatch.setenv("RED_MUSIC_DIR", str(tmp_path))
    assert music_dir() == tmp_path


# --- tools -------------------------------------------------------------------

def test_play_named_song(library):
    player = FakePlayer()
    reply = PlayMusic(player, library, shuffle=no_shuffle).run(query="get lucky")
    assert reply == "Playing Get Lucky."
    assert names(player.queue) == ["08 - Get Lucky.mp3"]


def test_play_artist_shuffles_their_songs(library):
    player = FakePlayer()
    shuffled = []
    reply = PlayMusic(player, library, shuffle=shuffled.append).run(query="Daft Punk")
    assert len(shuffled) == 1 and len(player.queue) == 3
    assert reply.startswith("Shuffling 3 songs matching Daft Punk, starting with ")


def test_play_without_query_shuffles_everything(library):
    player = FakePlayer()
    reply = PlayMusic(player, library, shuffle=no_shuffle).run()
    assert len(player.queue) == 9
    assert reply.startswith("Shuffling all 9 songs")


def test_play_filler_query_shuffles_everything(library):
    player = FakePlayer()
    PlayMusic(player, library, shuffle=no_shuffle).run(query="some music")
    assert len(player.queue) == 9


def test_play_no_match(library):
    player = FakePlayer()
    assert PlayMusic(player, library).run(query="metallica") == \
        "I couldn't find any music matching metallica."
    assert player.queue == []


def test_play_missing_folder(tmp_path):
    reply = PlayMusic(FakePlayer(), folder=lambda: tmp_path / "nope").run()
    assert reply.startswith("I can't find your music folder")


def test_play_empty_folder(tmp_path):
    assert PlayMusic(FakePlayer(), folder=lambda: tmp_path).run().startswith("There's no music")


def test_play_uses_folder_at_run_time(monkeypatch, library):
    monkeypatch.setenv("RED_MUSIC_DIR", str(library.root))
    player = FakePlayer()
    PlayMusic(player, shuffle=no_shuffle).run(query="halo")
    assert names(player.queue) == ["Halo.mp3"]


def test_player_error_becomes_a_reply(library):
    reply = PlayMusic(FakePlayer(fail="no audio output"), library).run()
    assert reply == "I couldn't play music: no audio output."


def test_query_is_never_a_path(library, tmp_path):
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"")
    player = FakePlayer()
    reply = PlayMusic(player, library).run(query=str(outside))
    assert outside not in player.queue
    assert reply.startswith("I couldn't find")


def test_stop_pause_resume_next(library):
    player = FakePlayer()
    stop, pause, resume, nxt = (StopMusic(player), PauseMusic(player),
                                ResumeMusic(player), NextSong(player))
    assert stop.run() == "No music is playing."
    assert pause.run() == "No music is playing."
    assert resume.run() == "No music is playing."
    assert nxt.run() == "No music is playing."

    PlayMusic(player, library, shuffle=no_shuffle).run(query="discovery")
    assert resume.run() == "The music isn't paused."
    assert pause.run() == "Paused."
    assert pause.run() == "The music is already paused."
    assert resume.run() == "Resuming One More Time."
    assert nxt.run() == "Playing Digital Love."
    assert nxt.run() == "That was the last song."
    PlayMusic(player, library).run()
    assert stop.run() == "Music stopped."
    assert stop.run() == "No music is playing."


def test_tools_share_the_default_player(monkeypatch):
    monkeypatch.setattr(music, "_shared_player", None)
    monkeypatch.setattr(music, "PygamePlayer", FakePlayer)
    assert PlayMusic().player is StopMusic().player is NextSong().player


def test_no_tool_is_destructive_and_schemas_are_closed():
    for cls in (PlayMusic, StopMusic, PauseMusic, ResumeMusic, NextSong):
        assert cls.destructive is False
        assert cls.args_schema["additionalProperties"] is False
    assert PlayMusic.args_schema["properties"]["query"]["maxLength"] == 100
    assert "required" not in PlayMusic.args_schema


# --- PygamePlayer logic, with a fake mixer --------------------------------------

class FakeError(Exception):
    pass


class FakeMusic:
    def __init__(self, bad=()):
        self.loaded, self.busy, self.paused, self.bad, self.log = None, False, False, bad, []

    def load(self, path):
        if Path(path).name in self.bad:
            raise FakeError("bad file")
        self.loaded = Path(path).name

    def play(self):
        self.busy = True
        self.log.append(self.loaded)

    def stop(self):
        self.busy = False

    def unload(self):
        self.loaded = None

    def pause(self):
        self.paused = True

    def unpause(self):
        self.paused = False

    def get_busy(self):
        return self.busy and not self.paused


def fake_player(bad=()):
    p = PygamePlayer(poll_seconds=0.01)
    p._music, p._error = FakeMusic(bad), FakeError
    return p


def test_pygame_player_plays_in_order_and_skips_bad_files():
    p = fake_player(bad={"b.mp3"})
    first = p.play([Path("a.mp3"), Path("b.mp3"), Path("c.mp3")])
    assert first == Path("a.mp3")
    assert p.next() == Path("c.mp3")
    assert p._music.log == ["a.mp3", "c.mp3"]
    assert p.next() is None and p.current is None


def test_pygame_player_all_bad():
    p = fake_player(bad={"a.mp3"})
    assert p.play([Path("a.mp3")]) is None
    assert p.stop() is False


def test_pygame_player_moves_on_when_a_song_ends():
    import time

    p = fake_player()
    p.play([Path("a.mp3"), Path("b.mp3")])
    p._music.busy = False          # song a ended
    deadline = time.monotonic() + 2
    while p.current != Path("b.mp3") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert p.current == Path("b.mp3")


def test_pygame_player_does_not_skip_while_paused():
    import time

    p = fake_player()
    p.play([Path("a.mp3"), Path("b.mp3")])
    assert p.pause() and p.paused
    time.sleep(0.05)
    assert p.current == Path("a.mp3")
    assert p.resume() and not p._music.paused
    assert p.stop() and p._music.loaded is None


# --- the real backend, silently -----------------------------------------------

def _write_wav(path: Path, seconds: float = 0.3, rate: int = 22050) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))


def test_real_pygame_backend_with_silent_driver(tmp_path):
    pytest.importorskip("pygame")
    songs = tmp_path / "Music"
    songs.mkdir()
    _write_wav(songs / "01 - First.wav")
    _write_wav(songs / "02 - Second.wav")
    (songs / "03 - Broken.mp3").write_bytes(b"not audio")
    # A separate process, so the dummy audio driver can't leak into other tests.
    code = f"""
import time
from pathlib import Path
from red.tools.music import Library, PlayMusic, NextSong, StopMusic, PygamePlayer
lib = Library(Path(r"{songs}"))
player = PygamePlayer(poll_seconds=0.02)
print(PlayMusic(player, lib, shuffle=lambda t: t.sort()).run())
deadline = time.monotonic() + 5
while player.current and player.current.name.startswith("01") and time.monotonic() < deadline:
    time.sleep(0.02)
print(player.current.name if player.current else None)
print(NextSong(player).run())
print(StopMusic(player).run())
"""
    env = dict(os.environ, SDL_AUDIODRIVER="dummy", PYGAME_HIDE_SUPPORT_PROMPT="1")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=env, timeout=60, cwd=Path(__file__).resolve().parent.parent)
    assert out.returncode == 0, out.stderr
    lines = out.stdout.strip().splitlines()
    assert lines == ["Shuffling all 3 songs, starting with First.",
                     "02 - Second.wav",            # moved on by itself
                     "That was the last song.",    # skipped the broken file
                     "No music is playing."]
