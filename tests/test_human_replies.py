"""Replies that sound like a person (plan.md 0.1 item 13): no invented life, no written laughter."""

import json
from datetime import datetime

import pytest

from red import speech as sp
from red.chat import Chat, human, invented_life, written_laughter

# Lines the real model wrote on 2026-11-13 (red.log and scripts/chat_eval.py runs).
INVENTED = [
    "Just waiting by my terminal for you to show up with something real.",
    "No movies playing, no music looping, just code and curiosity.",
    "Just sitting here waiting for you to finish your weekend project.",
    "Just waiting here at your desk, bored until you come back from lunch.",
    "Nothing much, just waiting here watching the clock tick down to lunch.",
    "Just finished reviewing some old logs.",
    "Nope, I'm stuck here guarding your screen until you actually do something.",
    "Fair enough... I'll sit here and wait until you're ready.",
    "Nothing special, just hanging out here on your PC.",
]
FINE = [
    "Not much. You?", "Ouch. Maybe fair, but ouch. What did I mess up?",
    "That sucks. Want to chat about what's bothering you, or do you need a distraction?",
    "Yeah, I'm here. Why'd you ask?", "Go, if you want to ship something this month.",
    "I don't sleep. Always here.", "Retro stuff's cool. You into a specific one?",
    "Did you get any sleep last night?", "Wait for it... okay, that was a bad joke.",
]


@pytest.mark.parametrize("line", INVENTED)
def test_invented_life_is_caught_and_dropped(line):
    assert invented_life(line)
    assert human(line) == ""


@pytest.mark.parametrize("line", FINE)
def test_normal_lines_pass(line):
    assert not invented_life(line)
    assert human(line) == line


def test_written_laughter_is_taken_out():
    assert written_laughter("Haha, glad to hear that.")
    assert human("Haha, glad to hear that.") == "Glad to hear that."
    assert human("*laughs* Fair.") == "Fair."
    assert human("lol") == ""
    assert not written_laughter("Ha. Fair point.")


class StreamLLM:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def stream_json(self, system, user, schema, **kw):
        self.calls.append(user)
        text = json.dumps({"reply": self.reply})
        for i in range(0, len(text), 7):
            yield text[i:i + 7]


class Spoken:
    cancelled = False

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def test_a_streamed_reply_never_speaks_the_invented_part():
    llm = StreamLLM("Just waiting by my terminal for you. Honestly, nothing deep. What's on yours?")
    stream = Spoken()
    with sp.speaking_to(stream):
        text = Chat(llm, now=lambda: datetime(2026, 11, 13, 12, 0)).reply("what's on your mind?")
    assert stream.said == ["Honestly, nothing deep.", "What's on yours?"]
    assert text == "Honestly, nothing deep. What's on yours?"


def test_prime_reads_the_chat_prompt_with_one_token():
    calls = []

    class LLM:
        def complete_json(self, system, user, schema, **kw):
            calls.append((system, kw))
            return "{"

    chat = Chat(LLM())
    chat.prime()
    assert calls[0][0] == chat.system() and calls[0][1]["max_tokens"] == 1
    Chat(None).prime()                                    # no model: nothing, no error


def test_the_clock_is_only_in_the_prompt_when_time_comes_up():
    llm = StreamLLM("Not much. You?")
    chat = Chat(llm, now=lambda: datetime(2026, 11, 13, 12, 0))
    with sp.speaking_to(Spoken()):
        chat.reply("what's up?")
        chat.reply("I already woke up man")
    assert "Friday" not in llm.calls[0]
    assert "It's Friday 12:00 PM" in llm.calls[1]
