"""Voice setup (learning how Whisper hears your "Hey Red"), personal phrases, and dismissals."""

import json
from datetime import datetime

import pytest

from red import voice_setup as vs
from red.smalltalk import DISMISS_REPLY, RUDE_REPLY, dismissal_reply
from red.wakeword import MAX_CLIP_SECONDS, HeyRedDetector, load_profile, match_score

NOW = datetime(2026, 11, 9, 10, 0)


# --- learning the profile ---------------------------------------------------------

def test_a_consistent_mishearing_is_learned():
    samples = [("Hey rat.", 0.8), ("Hey rat!", 0.9), ("Hey red.", 0.7), ("Hey rat", 1.0), ("Hey, Fred.", 0.8)]
    p = vs.learn_profile(samples, NOW)
    assert p["phrases"] == ["hey rat"]          # "hey fred" only came up once
    assert p["recognized"] == 4
    assert p["heard"][0] == "Hey rat."
    assert p["created"] == "2026-11-09T10:00:00"


def test_already_matching_needs_no_phrases():
    p = vs.learn_profile([("Hey Red.", 0.7)] * 5, NOW)
    assert p["phrases"] == [] and p["recognized"] == 5


def test_risky_phrases_are_never_learned():
    p = vs.learn_profile([("Hey there.", 0.8)] * 4 + [("Thank you.", 0.5)] * 3, NOW)
    assert p["phrases"] == []


def test_slow_speakers_get_a_longer_clip_limit():
    assert vs.learn_profile([("Hey red", 1.9)] * 3, NOW)["max_clip_seconds"] == 2.3
    assert vs.learn_profile([("Hey red", 0.6)] * 3, NOW)["max_clip_seconds"] == MAX_CLIP_SECONDS
    assert vs.learn_profile([("Hey red", 5.0)] * 3, NOW)["max_clip_seconds"] == 2.6


# --- the guided recording -----------------------------------------------------------

class Audio:
    def __init__(self, seconds):
        self.size = int(seconds * 16000)


def run(tmp_path, heard, sizes=None):
    sizes = list(sizes or [1.4] * len(heard))
    heard = list(heard)
    said, lines, chimes = [], [], []
    profile = vs.run_setup(
        tmp_path, record=lambda **kw: Audio(sizes.pop(0)) if sizes else Audio(0),
        transcribe=lambda audio: heard.pop(0), say=said.append, chime=lambda: chimes.append(1),
        out=lines.append, samples=4, max_attempts=6)
    return profile, said, lines, chimes


def test_setup_saves_a_profile_the_detector_reads(tmp_path):
    profile, said, lines, chimes = run(tmp_path, ["Hey rat.", "Hey rat.", "Hey red.", "Hey rat."])
    assert profile["phrases"] == ["hey rat"]
    assert len(chimes) == 4
    saved = json.loads((tmp_path / vs.PROFILE_NAME).read_text(encoding="utf-8"))
    assert saved["phrases"] == ["hey rat"] and load_profile(tmp_path) == saved
    assert said[-1].startswith("All set")
    assert any('Heard: "Hey rat."' in l for l in lines)


def test_silence_is_retried(tmp_path):
    profile, said, lines, chimes = run(tmp_path, ["Hey red"] * 4, sizes=[0, 1.2, 1.2, 0, 1.2, 1.2])
    assert profile["samples"] == 4
    assert sum("didn't hear anything" in l for l in lines) == 2


def test_too_little_speech_saves_nothing(tmp_path):
    profile, said, lines, chimes = run(tmp_path, ["Hey red"], sizes=[1.2, 0, 0, 0, 0, 0])
    assert profile is None
    assert not (tmp_path / vs.PROFILE_NAME).exists()
    assert "microphone" in said[-1]


# --- the detector uses the profile -------------------------------------------------

def test_personal_phrases_match():
    personal = frozenset({"hey rat"})
    assert match_score("Hey rat.", personal) == 0.9
    assert match_score("Hey rat, open it", personal) == 0.6
    assert match_score("Hey rat.") == 0.0                # without the profile: no match
    assert match_score("I saw a rat", personal) == 0.0


def test_a_broken_profile_is_ignored(tmp_path):
    (tmp_path / vs.PROFILE_NAME).write_text("{not json", encoding="utf-8")
    assert load_profile(tmp_path) == {}


def test_detector_uses_the_longer_clip_limit():
    d = HeyRedDetector(vad=lambda c: 0.0, transcribe=lambda c: "", max_clip_seconds=2.3,
                       personal=frozenset({"hey rat"}))
    assert d.max_clip_seconds == 2.3 and d.personal == {"hey rat"}


# --- go away -----------------------------------------------------------------------

@pytest.mark.parametrize("said, reply", [
    ("Sirs, fuck you, fuck off.", RUDE_REPLY),
    ("Fuck off from here", RUDE_REPLY),
    ("You're a nerd.", RUDE_REPLY),
    ("Just go from here, okay? I don't need your help.", DISMISS_REPLY),
    ("Go off", DISMISS_REPLY),
    ("Leave me alone", DISMISS_REPLY),
    ("Bye", DISMISS_REPLY),
    ("Shut up", DISMISS_REPLY),
])
def test_go_away(said, reply):
    assert dismissal_reply(said) == reply


@pytest.mark.parametrize("said", ["Open YouTube", "Play some fucking music", "Stop the music",
                                  "What's the weather, you idiot", "Search for go away by The Cure",
                                  "Shut down in 2 hours", ""])
def test_commands_are_not_dismissals(said):
    assert dismissal_reply(said) is None
