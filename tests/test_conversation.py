"""Talking like a friend (red.chat), "can you ...?" requests, yes and no, and reading the screen."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from fakes import FakeAsk, FakeRunner
from red import screen as sc
from red.chat import CHAT_SYSTEM, Chat
from red.executor import Executor
from red.router import Route
from red.smalltalk import is_ability_question, is_casual_yes, yes_intent
from red.tools.base import Tool, ToolRegistry
from red.tools.screen import DescribeScreen
from red.tools.system import Shutdown

NOW = datetime(2026, 11, 8, 21, 30)


class ChatLLM:
    def __init__(self, *replies, fail=False, no_temperature=False):
        self.replies = list(replies)
        self.calls = []
        self.fail = fail
        self.no_temperature = no_temperature

    def complete_json(self, system, user, schema, **kw):
        if self.no_temperature and kw:
            raise TypeError("unexpected keyword")
        self.calls.append((system, user, kw))
        if self.fail:
            raise OSError("model down")
        return json.dumps({"reply": self.replies.pop(0)})


# --- chat ------------------------------------------------------------------------

def test_chat_answers_like_a_friend_and_remembers():
    llm = ChatLLM("Pretty chill evening. How was yours?", "Ugh, sorry. Want to talk about it?")
    chat = Chat(llm, now=lambda: NOW)
    assert chat.reply("What's going on in your mind?") == "Pretty chill evening. How was yours?"
    assert chat.reply("Bad day at college.") == "Ugh, sorry. Want to talk about it?"
    system, prompt, kw = llm.calls[1]
    assert system == CHAT_SYSTEM
    assert "User: What's going on in your mind?" in prompt
    assert "Red: Pretty chill evening. How was yours?" in prompt
    assert prompt.endswith("The user now says: Bad day at college.")
    assert "Sunday 9:30 PM" in prompt
    assert kw["temperature"] > 0                       # not the routing's temperature 0


def test_the_persona_never_uses_stock_lines():
    assert "How can I assist you" in CHAT_SYSTEM          # listed as a thing never to say
    assert "Never make up things happening right now" in CHAT_SYSTEM


def test_commands_join_the_memory():
    llm = ChatLLM("Bring an umbrella, then!")
    chat = Chat(llm, now=lambda: NOW)
    chat.remember("What's the weather in Pune?", "Rain later, 24 degrees.")
    chat.reply("Should I go out?")
    assert "Red: Rain later, 24 degrees." in llm.calls[0][1]


def test_memory_is_forgotten_after_a_quiet_spell():
    t = [0.0]
    llm = ChatLLM("Hi again!")
    chat = Chat(llm, clock=lambda: t[0], forget_after=60, now=lambda: NOW)
    chat.remember("old secret", "noted")
    t[0] = 61
    chat.reply("Hello")
    assert "old secret" not in llm.calls[0][1]


def test_memory_is_bounded():
    chat = Chat(None, max_turns=4)
    for i in range(10):
        chat.remember(f"q{i}", f"a{i}")
    assert len(chat.turns) == 4 and chat.turns[-1] == ("Red", "a9")


def test_chat_falls_back_when_the_model_fails():
    assert Chat(ChatLLM(fail=True)).reply("hey", fallback="I'm here.") == "I'm here."
    assert "train of thought" in Chat(None).reply("hey")


def test_chat_works_with_clients_without_temperature():
    llm = ChatLLM("Sure thing.", no_temperature=True)
    assert Chat(llm, now=lambda: NOW).reply("hi") == "Sure thing."


def test_chat_replies_are_cleaned_for_speech():
    llm = ChatLLM("**Hey!** - one. Two. Three. Four. Five.")
    reply = Chat(llm, now=lambda: NOW).reply("hi")
    assert "*" not in reply and reply.count(".") <= 3


# --- "can you ...?" -------------------------------------------------------------

@pytest.mark.parametrize("said", [
    "Can you help me with turning off my laptop after 3 hours?",
    "I'll tell you to turn off my laptop after 3 hours, will you do that?",
    "Could you open YouTube?",
    "Are you able to lock my PC?",
    "Is it possible to set a timer?",
])
def test_ability_questions(said):
    assert is_ability_question(said)


@pytest.mark.parametrize("said", ["Turn off my laptop in 3 hours", "Open YouTube", "What can you do?",
                                  "Set a timer for 5 minutes"])
def test_commands_are_not_ability_questions(said):
    assert not is_ability_question(said)


@pytest.mark.parametrize("said, yes", [("Yeah, go ahead.", True), ("Sure.", True), ("Yes please", True),
                                       ("Do it", True), ("No.", False), ("maybe", False), (None, False)])
def test_casual_yes(said, yes):
    assert is_casual_yes(said) is yes


class Opener(Tool):
    name = "open_url"
    description = "open"
    args_schema = {"type": "object"}

    def __init__(self):
        self.ran = []

    def run(self, **kw):
        self.ran.append(kw)
        return "Opening YouTube."


class Weather(Tool):
    name = "weather"
    description = "weather"
    args_schema = {"type": "object"}

    def run(self, **kw):
        return "Sunny."


def executor(answers, *tools):
    ask = FakeAsk(*answers)
    return Executor(ToolRegistry(list(tools)), ask=ask), ask


@pytest.mark.parametrize("said, yes", [
    ("Yeah, you don't need my permission. Go ahead.", True),   # said 2026-11-08 22:24
    ("yes", True), ("Yep, do it", True), ("Sure, why not", True), ("No problem, go for it", True),
    ("okay", True), ("Of course you can", True),
    ("No.", False), ("Nah, don't", False), ("Stop", False), ("Cancel that", False),
    ("Yes, no wait, don't", False), ("Don't do it", False), ("I don't know", False),
    ("maybe", None), ("", None), (None, None),
])
def test_yes_intent_reads_the_whole_sentence(said, yes):
    assert yes_intent(said) is yes


@pytest.mark.parametrize("said, yes", [("okay", None), ("please", None), ("Yeah, go ahead", True),
                                       ("Sure.", True), ("y", True), ("No, don't.", False)])
def test_strict_yes_intent_for_risky_actions(said, yes):
    assert yes_intent(said, strict=True) is yes


@pytest.mark.parametrize("said", ["Could you open YouTube?", "Can you open YouTube?", "Open YouTube"])
def test_harmless_requests_just_run(said):
    tool = Opener()
    ex, ask = executor([], tool)
    assert ex.execute(said, Route("open_url", {"url": "x"}, False)) == "Opening YouTube."
    assert ask.questions == []                         # no "Should I go ahead?"
    assert tool.ran == [{"url": "x"}]


def test_the_podcast_request_from_the_log_runs_without_asking():
    # 22:24: Red asked "Should I go ahead?", heard "Yeah, you don't need my
    # permission. Go ahead." and answered "Okay, I won't." Now it just runs.
    tool = Opener()
    ex, ask = executor(["Yeah, you don't need my permission. Go ahead."], tool)
    ex.execute("Can you open a podcast to me that will make my loneliness go away?",
               Route("open_url", {"url": "x"}, False))
    assert ask.questions == [] and tool.ran == [{"url": "x"}]


def shutdown_executor(*answers):
    runner = FakeRunner()
    now = lambda: datetime(2026, 11, 8, 21, 40)  # noqa: E731
    ex, ask = executor(list(answers), Shutdown(runner=runner, now=now))
    return ex, ask, runner


SHUTDOWN_3H = Route("shutdown", {"minutes": 180}, True)


def test_a_risky_request_asks_once_saying_what_and_when():
    ex, ask, runner = shutdown_executor("Yeah, go ahead.")
    reply = ex.execute("I'll tell you to turn off my laptop after 3 hours, will you do that?", SHUTDOWN_3H)
    assert [q for q, _ in ask.questions] == ["Shut down in 3 hours (at 12:40 AM tomorrow)?"]
    assert "12:40 AM" in reply and runner.calls          # asked once, then scheduled


@pytest.mark.parametrize("answer, reply", [("okay", "Cancelled."), ("No, don't.", "Cancelled."),
                                           ("Yes, no wait.", "Cancelled."),
                                           (None, "No answer, so I cancelled it.")])
def test_a_risky_request_needs_a_clear_yes(answer, reply):
    ex, ask, runner = shutdown_executor(answer)
    assert ex.execute("Shut down in 3 hours", SHUTDOWN_3H) == reply
    assert runner.calls == []


def test_look_ups_are_just_answered():
    ex, ask = executor([], Weather())
    assert ex.execute("Can you check the weather?", Route("weather", {}, False)) == "Sunny."
    assert ask.questions == []


# --- the screen ------------------------------------------------------------------

class Grab:
    def __init__(self):
        self.saved = []

    def __call__(self):
        return SimpleNamespace(save=lambda path: (Path(path).write_bytes(b"png"), self.saved.append(Path(path))))


def test_screen_text_reads_and_deletes_the_screenshot(tmp_path):
    grab = Grab()
    seen = []

    def runner(cmd, **kw):
        image = Path(kw["env"]["RED_OCR_IMAGE"])
        seen.append(image.exists())
        return SimpleNamespace(returncode=0, stdout="YouTube\n  Home \n\nRecommended\n".encode())

    lines = sc.screen_text(tmp_path, grab=grab, runner=runner)
    assert lines == ["YouTube", "Home", "Recommended"]
    assert seen == [True]
    assert not grab.saved[0].exists()                  # never left on disk


def test_screen_text_failure_still_deletes(tmp_path):
    grab = Grab()
    with pytest.raises(OSError):
        sc.screen_text(tmp_path, grab=grab, runner=lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=b""))
    assert not grab.saved[0].exists()


def test_ocr_script_takes_the_path_only_from_the_environment():
    assert "$env:RED_OCR_IMAGE" in sc.OCR_SCRIPT
    assert sc.ocr_command()[:3] == ["powershell.exe", "-NoProfile", "-NonInteractive"]


def test_read_screen_keeps_the_title_when_ocr_fails(tmp_path):
    def broken(path):
        raise OSError("no OCR")
    info = sc.read_screen(tmp_path, window=lambda: ("YouTube - Google Chrome", "chrome"), text=broken)
    assert info.title.startswith("YouTube") and not info.ocr_ok
    assert "couldn't be read" in info.as_prompt()


def test_prompt_is_capped():
    info = sc.ScreenInfo("t", "app", ["x" * 1000] * 10)
    assert len(info.as_prompt()) < sc.MAX_TEXT + 300


class AnswerLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user))
        return json.dumps({"answer": "You're on YouTube's home page, just browsing."})


def test_describe_screen_tool(tmp_path):
    llm = AnswerLLM()
    info = sc.ScreenInfo("YouTube - Google Chrome", "chrome", ["Home", "Shorts", "Recommended"])
    tool = DescribeScreen(llm=llm, read=lambda cache: info, cache_dir=tmp_path)
    assert tool.run() == "You're on YouTube's home page, just browsing."
    prompt = llm.calls[0][1]
    assert "YouTube - Google Chrome" in prompt and "Recommended" in prompt
    assert prompt.startswith("The user asked: What's on my screen?")


def test_describe_screen_with_nothing_to_see(tmp_path):
    from red.tools.base import ToolError
    tool = DescribeScreen(llm=AnswerLLM(), read=lambda cache: sc.ScreenInfo(), cache_dir=tmp_path)
    with pytest.raises(ToolError):
        tool.run()
