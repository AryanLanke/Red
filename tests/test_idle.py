"""Idle life and temper (red/idle.py), driven with a fake clock: nothing real is looked at or played."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from red import companions, events
from red.chat import invented_life
from red import idle as idlemod
from red.idle import (ACTIONS, GRUMBLES, IdleLife, SONG_EVERY, Song, effective_chattiness, make_music,
                      media_playing)


class World:
    """A fake clock, a fake `now`, and the things Windows would tell us."""

    def __init__(self):
        self.t = 1000.0
        self.wall = datetime(2026, 11, 13, 15, 0, 0)
        self.idle = 5.0             # seconds since the last keyboard or mouse input
        self.blocked = False
        self.busy = False
        self.playing = False
        self.said = []
        self.say_ok = True

    def advance(self, seconds):
        self.t += seconds
        self.wall += timedelta(seconds=seconds)

    def say(self, text):
        if not self.say_ok:
            return False
        self.said.append(text)
        return True


@pytest.fixture(autouse=True)
def _events():
    events.clear()
    yield
    events.clear()


def life_for(tmp_path, cid="red", world=None, music=None, level="companion", seed=1, **pack):
    world = world or World()
    base = companions.load(cid, tmp_path)
    if pack:
        from dataclasses import replace
        base = replace(base, **pack)
    life = IdleLife(tmp_path, lambda: base, world.say, music=music, level=lambda: level,
                    idle=lambda: world.idle, blocked=lambda: world.blocked, busy=lambda: world.busy,
                    playing=lambda: world.playing, now=lambda: world.wall, clock=lambda: world.t,
                    rng=random.Random(seed))
    return life, world


def record():
    seen = []
    events.on("idle_action", lambda name: seen.append(name))
    return seen


def run(life, world, minutes, step=10.0):
    """Tick every `step` seconds for `minutes`; returns everything that happened."""
    out = []
    for _ in range(int(minutes * 60 / step)):
        world.advance(step)
        out.extend(life.tick())
    return out


# --- small actions ----------------------------------------------------------------------------------------

def test_a_companion_at_the_pc_now_and_then_does_small_things(tmp_path):
    life, world = life_for(tmp_path)
    seen = record()
    got = [x for x in run(life, world, 60) if x in ACTIONS]
    assert seen == got and 10 <= len(seen) <= 60, "every 45-150 s, roughly"
    assert set(seen) <= set(ACTIONS) and "look_around" in seen
    assert all(a != b for a, b in zip(seen, seen[1:])), "never the same action twice in a row"
    assert "doze" not in seen, "the user is typing, so no dozing off"


def test_it_dozes_off_only_when_the_user_has_been_quiet_a_few_minutes(tmp_path):
    life, world = life_for(tmp_path)
    world.idle = 4 * 60
    seen = record()
    run(life, world, 60)          # the idle number is fixed at 4 minutes: "at the PC, but quiet"
    assert "doze" in seen
    dozes = [i for i, n in enumerate(seen) if n == "doze"]
    assert len(dozes) <= 6, "not again within ten minutes"


def test_nothing_happens_while_the_user_is_away(tmp_path):
    life, world = life_for(tmp_path)
    world.idle = 11 * 60
    seen = record()
    assert run(life, world, 120) == [] and seen == []


@pytest.mark.parametrize("reason", ["blocked", "busy"])
def test_nothing_during_a_game_a_call_or_a_turn(tmp_path, reason):
    life, world = life_for(tmp_path)
    setattr(world, reason, True)
    seen = record()
    assert run(life, world, 120) == [] and seen == []
    setattr(world, reason, False)
    assert run(life, world, 10), "and it carries on afterwards"


def test_blocked_is_only_asked_now_and_then(tmp_path):
    asked = []
    life, world = life_for(tmp_path)
    life._blocked = lambda: asked.append(1) or True
    run(life, world, 30)
    assert len(asked) <= 30 + 1, "once a minute at most, not every tick"


def test_the_packs_switches_turn_things_off(tmp_path):
    life, world = life_for(tmp_path, idle={"look_around": False, "sleep": False, "wander": True,
                                           "grumble": False, "music": False})
    world.idle = 4 * 60
    seen = record()
    run(life, world, 120)
    assert set(seen) == {"wander"}


def test_hum_is_for_music_lovers(tmp_path):
    for cid, hums in (("red", True), ("remy", True), ("winston", False), ("bruno", False)):
        life, world = life_for(tmp_path, cid=cid, seed=3)
        seen = record()
        run(life, world, 300)
        assert ("hum" in seen) == (hums and companions.load(cid, tmp_path).allows("music")), cid
        events.clear()


# --- temper ---------------------------------------------------------------------------------------------

def test_it_grumbles_when_ignored_but_at_most_once_an_hour(tmp_path):
    life, world = life_for(tmp_path)               # Red: medium temper, 40 minutes
    run(life, world, 39)
    assert world.said == []
    run(life, world, 3)
    assert len(world.said) == 1 and world.said[0] in GRUMBLES["red"]
    run(life, world, 55)
    assert len(world.said) == 1, "not again within the hour"
    run(life, world, 8)
    assert len(world.said) == 2
    # Over three hours of being ignored: ~one an hour, never more.
    life2, world2 = life_for(tmp_path / "again")
    run(life2, world2, 180)
    assert 3 <= len(world2.said) <= 4


def test_temper_sets_how_fast_it_gets_annoyed(tmp_path):
    for temper, minutes in (("high", 20), ("medium", 40), ("low", 90)):
        life, world = life_for(tmp_path / temper, temper=temper, idle=dict.fromkeys(companions.IDLE_SWITCHES, True))
        run(life, world, minutes - 2)
        assert world.said == [], temper
        run(life, world, 4)
        assert len(world.said) == 1, temper


def test_talking_to_it_resets_the_wait(tmp_path):
    life, world = life_for(tmp_path)
    run(life, world, 35)
    life.heard("hey, what's up")
    run(life, world, 35)
    assert world.said == []
    run(life, world, 10)
    assert len(world.said) == 1


@pytest.mark.parametrize("said", ["I'm so stressed today", "rough day", "I'm really sad", "I'm feeling lonely",
                                  "leave me alone"])
def test_no_grumbling_after_the_user_says_theyre_upset(tmp_path, said):
    life, world = life_for(tmp_path)
    life.heard(said)
    run(life, world, 100)
    assert world.said == []
    run(life, world, 40)                           # two hours after they spoke: back to normal
    assert len(world.said) == 1


def test_a_sad_conversation_also_stops_grumbles(tmp_path):
    life, world = life_for(tmp_path)
    events.on("emotion", life.felt)
    events.emit("emotion", name="sad", strength=0.7)
    run(life, world, 100)
    assert world.said == []


def test_it_grumbles_only_when_the_user_is_busy_with_other_things(tmp_path):
    life, world = life_for(tmp_path)
    world.idle = 5 * 60                            # at the PC, but not touching it: no one to grumble at
    run(life, world, 100)
    assert world.said == []


def test_quiet_level_and_the_off_switch_mean_no_grumbles(tmp_path):
    life, world = life_for(tmp_path, level="quiet")
    run(life, world, 100)
    assert world.said == []
    life, world = life_for(tmp_path / "x", idle={"grumble": False})
    run(life, world, 100)
    assert world.said == []
    life, world = life_for(tmp_path / "y", cid="remy")      # Remy's pack has grumble off
    run(life, world, 100)
    assert world.said == []


def test_no_grumble_in_a_call_or_a_game_and_none_is_spent(tmp_path):
    life, world = life_for(tmp_path)
    world.blocked = True
    run(life, world, 60)
    assert world.said == []
    world.blocked = False
    run(life, world, 2)
    assert len(world.said) == 1, "it was still due once the call ended"


def test_a_busy_voice_keeps_the_grumble_for_later(tmp_path):
    life, world = life_for(tmp_path)
    world.say_ok = False
    run(life, world, 60)
    world.say_ok = True
    run(life, world, 1)
    assert len(world.said) == 1


def test_the_hour_survives_a_restart(tmp_path):
    life, world = life_for(tmp_path)
    run(life, world, 45)
    assert len(world.said) == 1
    life2 = IdleLife(tmp_path, life.companion, world.say, level=lambda: "companion", idle=lambda: world.idle,
                     blocked=lambda: False, now=lambda: world.wall, clock=lambda: world.t, rng=random.Random(2))
    run(life2, world, 50)                         # a new process: its own 40 minutes pass, the hour isn't up
    assert len(world.said) == 1


def test_grumbles_are_polite_and_never_invent_a_life():
    for cid, lines in GRUMBLES.items():
        for line in lines + idlemod.GENERIC_GRUMBLES:
            assert not invented_life(line), line
            assert not any(w in line.lower() for w in ("stupid", "idiot", "shut up", "hate you")), line


def test_a_grumble_shows_in_the_face(tmp_path):
    life, world = life_for(tmp_path)
    seen = []
    events.on("emotion", lambda name, strength: seen.append((name, strength)))
    run(life, world, 45)
    assert ("angry", 0.5) in seen


# --- a song of its own -------------------------------------------------------------------------------------

def song_maker(played, text="Putting on Come Together."):
    return lambda c: Song(text, lambda: played.append(text), "online")


def test_it_puts_on_a_song_says_so_first_and_not_twice_in_two_hours(tmp_path):
    played = []
    life, world = life_for(tmp_path, music=song_maker(played))
    life.heard("hi")
    order = []
    life._say = lambda text: order.append(("said", text)) or True
    life.heard("hi")
    songs = 0
    for _ in range(int(5 * 3600 / 10)):
        world.advance(10)
        if not (world.t % 600 < 10):
            pass
        life.heard("still here")                    # the user keeps chatting, so no grumbles
        if "song" in life.tick():
            songs += 1
            assert order[-1] == ("said", "Putting on Come Together."), "said before it plays"
            assert played, "and it played"
    assert 2 <= songs <= 3, "at most one every two hours over five hours"


def test_the_song_gap_is_two_hours_of_wall_clock(tmp_path):
    played = []
    life, world = life_for(tmp_path, music=song_maker(played))
    life._mark("song_at")
    for _ in range(int(110 * 60 / 10)):
        world.advance(10)
        life.heard("x")
        assert "song" not in life.tick(), "under two hours since the last one"


def test_songs_only_at_the_companion_level(tmp_path):
    for level in ("quiet", "friendly", "chatty"):
        played = []
        life, world = life_for(tmp_path / level, music=song_maker(played), level=level)
        for _ in range(int(3 * 3600 / 10)):
            world.advance(10)
            life.heard("x")
            life.tick()
        assert played == [], level


def test_only_music_loving_companions_with_the_switch_on(tmp_path):
    played = []
    life, world = life_for(tmp_path, cid="winston", music=song_maker(played))
    for _ in range(int(3 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert played == []


def test_no_song_while_something_else_plays_or_in_a_call(tmp_path):
    played = []
    life, world = life_for(tmp_path, music=song_maker(played))
    world.playing = True
    for _ in range(int(2 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert played == []
    world.playing = False
    world.blocked = True
    for _ in range(int(2 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert played == []
    world.blocked = False
    for _ in range(int(3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert played, "once the call is over it picks its moment"


def test_it_does_not_play_if_it_could_not_say_so_first(tmp_path):
    played = []
    life, world = life_for(tmp_path, music=song_maker(played))
    world.say_ok = False
    for _ in range(int(2 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert played == []


def test_a_song_is_announced_with_its_hum_and_a_happy_face(tmp_path):
    played = []
    life, world = life_for(tmp_path, music=song_maker(played))
    feelings, actions = [], record()
    events.on("emotion", lambda name, strength: feelings.append(name))
    for _ in range(int(2 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        life.tick()
    assert "hum" in actions and "happy" in feelings and played


def test_stop_stops_the_song_it_put_on(tmp_path):
    played, stopped = [], []
    life, world = life_for(tmp_path, music=song_maker(played))
    assert life.stop_reply("stop", lambda: stopped.append(1)) is None, "no song yet: left to the usual handling"
    for _ in range(int(2 * 3600 / 10)):
        world.advance(10)
        life.heard("x")
        if "song" in life.tick():
            break
    assert life.song_active()
    for said in ("stop", "Stop.", "okay, stop", "turn it off", "stop the music"):
        life._song_started = world.t
        assert life.stop_reply(said, lambda: stopped.append(1)) == "Okay, stopped."
    assert len(stopped) == 5
    assert life.stop_reply("stop", lambda: stopped.append(1)) is None, "only the song, once"
    life._song_started = world.t
    assert life.stop_reply("stop the timer", lambda: None) is None
    world.advance(31 * 60)
    assert not life.song_active()


# --- the real parts, with fakes -------------------------------------------------------------------------------

class FakeTool:
    def __init__(self, name):
        self.name, self.calls = name, []

    def run(self, query):
        self.calls.append(query)
        return "ok"

    def take_later(self):
        return None


class FakeRegistry:
    def __init__(self, *names):
        self.tools = {n: FakeTool(n) for n in names}

    def __contains__(self, name):
        return name in self.tools

    def get(self, name):
        return self.tools[name]


class W:
    def __init__(self, exe, title):
        self.exe, self.title = exe, title


def test_make_music_plays_a_local_file_when_there_is_music(tmp_path):
    from red.tools.local_music import PlayLocal
    root = tmp_path / "Music"
    root.mkdir()
    (root / "01 - Get Lucky.mp3").write_bytes(b"x")
    opened = []
    local = PlayLocal(root=root, startfile=opened.append, rng=random.Random(1))
    choose = make_music(FakeRegistry(), random.Random(1), local=local, windows=lambda: [])
    song = choose(companions.load("red", tmp_path))
    assert song.source == "local" and "Get Lucky" in song.announce and opened == []
    song.play()
    assert [Path(p).name for p in opened] == ["01 - Get Lucky.mp3"]


def test_make_music_falls_back_to_youtube_with_a_famous_song(tmp_path):
    from red.tools.local_music import PlayLocal
    local = PlayLocal(root=tmp_path / "nothing", startfile=lambda p: None)
    registry = FakeRegistry("play_online")
    choose = make_music(registry, random.Random(1), local=local, windows=lambda: [])
    song = choose(companions.load("red", tmp_path))
    assert song.source == "online" and song.announce.startswith(("Putting on", "I'm putting on")) or "Trust me" in song.announce
    song.play()
    assert registry.get("play_online").calls[0] in [q for _, q in idlemod.SONGS["red"]]


def test_make_music_uses_spotify_only_when_it_is_open(tmp_path):
    from red.tools.local_music import PlayLocal
    local = PlayLocal(root=tmp_path / "nothing", startfile=lambda p: None)
    registry = FakeRegistry("spotify_search")
    assert make_music(registry, random.Random(1), local=local, windows=lambda: [])(companions.load("red", tmp_path)) is None
    choose = make_music(registry, random.Random(1), local=local, windows=lambda: [W("spotify.exe", "Spotify Free")])
    song = choose(companions.load("remy", tmp_path))
    assert song.source == "spotify" and "on Spotify" in song.announce
    song.play()
    assert registry.get("spotify_search").calls


def test_every_announcement_and_song_is_clean(tmp_path):
    for cid, lines in {**idlemod.ANNOUNCE, "generic": idlemod.GENERIC_ANNOUNCE}.items():
        for line in lines:
            assert not invented_life(line.format(title="X")), line
    assert all(isinstance(t, tuple) and len(t) == 2 for songs in idlemod.SONGS.values() for t in songs)


def test_media_playing_guesses_from_window_titles():
    assert media_playing(lambda: [W("spotify.exe", "Daft Punk - Get Lucky")])
    assert not media_playing(lambda: [W("spotify.exe", "Spotify Free")])
    assert media_playing(lambda: [W("chrome.exe", "Believer - YouTube")])
    assert not media_playing(lambda: [W("code.exe", "idle.py - Red")])
    assert not media_playing(lambda: (_ for _ in ()).throw(OSError("no desktop")))


def test_effective_chattiness_prefers_what_the_user_set(tmp_path):
    red = companions.load("red", tmp_path)
    assert effective_chattiness("friendly", False, red) == "companion"
    assert effective_chattiness("friendly", True, red) == "friendly"
    assert effective_chattiness("friendly", False, None) == "friendly"
