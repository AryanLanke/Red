"""red/conversation.py: conversation mode, the zipped mouth, and who a sentence is for. No mic, no speakers."""

import json

import numpy as np
import pytest

from red import conversation as conv
from red import events

VSCODE = "conversation.py - n2-conversation - visual studio code code.exe"
DESKTOP = "program manager explorer.exe"

# What the user said to Claude while Red heard it (red.log, 2026-11-13 21:19-21:20 and 22:49-22:51).
# Only the start of each was transcribed (the wake stage hears 1.3 s); the full lines are longer.
DICTATED = [
    "Start the next task and commit it when the tests pass",
    "When I said you're crazy, I meant the replies sound written",
    "commands for human sentences should go straight to the chat",
    "and now you can do other things in the plan",
    "but before that I want you to check the logs",
    "It could be committed and pushed to main",
    "Also I would get the tests running first",
    "Everything is done in the session, now make the report",
    "Make this project faster",
    "Session B has done some work on the companions",
    "and it has done some work.",
    "and now we have created some new sound packs",
    "working on other another issue with the wake word",
    "Sometimes they don't listen to the plan and change other files",
    "There should be automatic commits after every task",
    "and now I want you to install the installer",
    "You don't need to take my permission for the small edits",
]
# What the user said to Red with VS Code in front (commands.jsonl): these must still be answered.
FOR_RED = ["How are you?", "What's going on your mind right now?", "You're crazy!", "Open YouTube.",
           "Play some music.", "What time is it?", "Tell me a joke.", "You so mean", "Don't sleep, OK?",
           "Should I tell you what did you do?", "Open my downloads.", "Can you read what's on my screen right now?",
           "Check the weather in London for tomorrow.", "Remind me to call mom at five.",
           "Tell me about the history of the Roman empire.", "Switch to Remy.", "Send a message to Tom."]


@pytest.fixture(autouse=True)
def no_handlers():
    events.clear()
    yield
    events.clear()


def collect(*names):
    got = []
    for name in names:
        events.on(name, lambda _n=name, **kw: got.append((_n, kw)))
    return got


# --- the phrases -------------------------------------------------------------------------------

@pytest.mark.parametrize("said, kind", [
    ("Zip it.", "zip"), ("Not now.", "zip"), ("I'm not talking to you.", "zip"), ("Not now, Red.", "zip"),
    ("I wasn't talking to you", "zip"), ("That's all.", "end"), ("Stop listening.", "end"), ("Bye!", "end"),
    ("Not you.", "end"), ("Okay, that's all, thanks.", "end"), ("Bye Red.", "end"),
    ("Not now, but remind me at five.", None), ("Say bye to Tom.", None), ("Open YouTube.", None),
    ("No.", None), ("", None),
])
def test_end_phrases(said, kind):
    assert conv.end_phrase(said) == kind


# --- who it is for -------------------------------------------------------------------------------

@pytest.mark.parametrize("said, who", [
    ("Claude, make the button blue.", "claude"), ("Hey ChatGPT, what's a monad?", "chatgpt"),
    ("Copilot, summarise this page.", "copilot"), ("Hey Siri, set a timer.", "siri"),
    ("Alexa, turn the lights off.", "alexa"), ("OK Google, what's the weather?", "google"),
    ("Cloud, write the tests first.", "claude"), ("Mom, dinner's ready?", "mom"),
    ("Hey Red, open YouTube.", None), ("Red, ask Claude later.", None), ("Open Claude.", None),
    ("Hey, Copilot, open the file.", "copilot"), ("Chat GPT, explain this.", "chatgpt"),
    ("Tell Claude I'm busy.", None), ("What's the cloud made of?", None), ("How are you?", None),
])
def test_addressed_elsewhere(said, who):
    assert conv.addressed_elsewhere(said, contacts=["Mom", "Tom"], own_names=["red", "remy", "asha"]) == who


def test_dictation_to_claude_is_not_for_red():
    flagged = [line for line in DICTATED if conv.dictation_like(line, VSCODE)]
    assert len(flagged) >= 0.8 * len(DICTATED), set(DICTATED) - set(flagged)


def test_talk_to_red_with_vscode_in_front_is_still_answered():
    assert [line for line in FOR_RED if conv.dictation_like(line, VSCODE)] == []


def test_dictation_rule_needs_an_editor_or_chat_in_front():
    assert not any(conv.dictation_like(line, DESKTOP) for line in DICTATED)
    assert conv.dictation_window("claude - microsoft edge msedge.exe")
    assert conv.dictation_window("windows powershell windowsterminal.exe")


def test_saying_red_overrides_the_dictation_rule():
    line = "Red, make the button blue and commit it when the tests pass"
    assert not conv.dictation_like(line, VSCODE, own_names=["red"])
    assert conv.dictation_like(line.replace("Red, ", ""), VSCODE, own_names=["red"])


# --- the echo guard -----------------------------------------------------------------------------

def test_echo_of_reds_own_reply_is_caught():
    said = "Only if you promise to stop being dramatic about it first."
    assert conv.is_echo("stop being dramatic about it first", said)
    assert conv.is_echo("Only if you promise to stop being dramatic", said)
    assert not conv.is_echo("I'm not being dramatic", said)
    assert not conv.is_echo("Okay.", said)                 # too short to tell
    assert not conv.is_echo("What did you say?", said)


# --- conversation mode and the zip ------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_start_and_end_emit_and_play(tmp_path):
    got = collect("conversation", "zipped")
    played = []
    c = conv.Conversation(tmp_path / "mic.json", sound=played.append)
    assert c.begin("button") and c.active and not c.zipped
    assert not c.begin("button")                           # already on
    assert c.end("button")
    assert not c.active and c.zipped and c.stop.is_set()
    assert played == ["start", "end"]
    assert got == [("conversation", {"on": True, "reason": "button"}),
                   ("conversation", {"on": False, "reason": "button"}), ("zipped", {"on": True})]
    assert json.loads((tmp_path / "mic.json").read_text())["zipped"] is True


def test_zip_is_remembered_and_keeps_the_mute_flag(tmp_path):
    path = tmp_path / "mic.json"
    path.write_text(json.dumps({"muted": False}))
    c = conv.Conversation(path, sound=lambda k: None)
    c.zip("said")
    assert json.loads(path.read_text()) == {"muted": False, "zipped": True}
    assert conv.Conversation(path).zipped                   # after a restart, still zipped
    c.unzip()
    assert json.loads(path.read_text())["zipped"] is False


def test_starting_unzips(tmp_path):
    got = collect("zipped")
    c = conv.Conversation(tmp_path / "mic.json")
    c.zip()
    c.begin()
    assert not c.zipped and got == [("zipped", {"on": True}), ("zipped", {"on": False})]


def test_zip_during_conversation_ends_it(tmp_path):
    played = []
    c = conv.Conversation(tmp_path / "mic.json", sound=played.append)
    c.begin()
    c.zip("said")
    assert not c.active and c.zipped and c.end_reason == "said"
    assert played == ["start", "end"]


def test_idle_clock(tmp_path):
    clock = Clock()
    c = conv.Conversation(None, idle_seconds=60, clock=clock)
    c.begin()
    clock.t += 45
    assert c.idle_left() == pytest.approx(15)
    c.heard()
    assert c.idle_left() == pytest.approx(60)


def test_a_broken_sound_never_breaks_it(tmp_path):
    def boom(kind):
        raise RuntimeError("no speakers")
    c = conv.Conversation(None, sound=boom)
    assert c.begin() and c.end("idle")


# --- another app has the microphone ---------------------------------------------------------------

def test_guard_pauses_and_resumes(tmp_path):
    got = collect("paused")
    busy = [False, True, True, False]
    calls = []
    c = conv.Conversation(None)
    c.begin()
    guard = conv.OtherAppGuard(c, pause=lambda: calls.append("pause"), resume=lambda: calls.append("resume"),
                               check=lambda: busy.pop(0))
    assert guard.tick() is False
    assert guard.tick() is True and c.paused and c.stop.is_set()
    assert guard.tick() is True
    assert guard.tick() is False and not c.paused
    import time
    for _ in range(50):
        if "pause" in calls:
            break
        time.sleep(0.01)
    assert sorted(calls) == ["pause", "resume"]
    assert got == [("paused", {"on": True}), ("paused", {"on": False})]
    assert guard.checks == 4


def test_guard_treats_a_failing_check_as_nobody():
    c = conv.Conversation(None)
    guard = conv.OtherAppGuard(c, pause=lambda: None, resume=lambda: None, check=lambda: 1 / 0)
    assert guard.tick() is False


# --- the zipper ----------------------------------------------------------------------------------

def test_zipper_tone_is_short_and_not_too_loud():
    tone, rate = conv.zipper_tone()
    assert rate == 22_050 and 0.25 < tone.size / rate < 0.4
    assert np.abs(tone).max() <= 0.13 and tone.dtype == np.float32
    assert np.abs(tone[:10]).max() < 0.02                        # faded in: no click
