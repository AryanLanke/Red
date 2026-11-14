"""Emotion tags (red/emotion.py): cut before speech, a cheap guess as the fallback, an event for the avatar."""

import json

import pytest

from red import emotion, events
from red import speech as sp
from red.chat import Chat, human


@pytest.fixture(autouse=True)
def _events():
    events.clear()
    yield
    events.clear()


@pytest.mark.parametrize("text, clean, tag", [
    ("[happy] Nice one.", "Nice one.", "happy"),
    ("[Annoyed] Oh, so now you remember me.", "Oh, so now you remember me.", "annoyed"),
    ("[ excited ] Let's go!", "Let's go!", "happy"),
    ("Fine. [sigh] Go on.", "Fine. Go on.", None),
    ("[mild sigh] Hmm.", "Hmm.", None),
    ("No tag here.", "No tag here.", None),
    ("[neutral]", "", "neutral"),
    ("Item [1] stays.", "Item [1] stays.", None),
])
def test_split_tag(text, clean, tag):
    assert emotion.split_tag(text) == (clean, tag)


def test_a_tag_is_never_spoken():
    assert human("[happy] Nice one.") == "Nice one."
    assert human("[sigh] Fine.") == "Fine."
    assert human("[happy]") == ""


@pytest.mark.parametrize("text, name", [
    ("Oof, sorry about that.", "sad"), ("Wow, no way!", "surprised"), ("Ugh, seriously.", "angry"),
    ("Congrats, that's great news!", "happy"), ("Hmm, good question.", "thinking"), ("Oops, my bad.", "shy"),
    ("The file is in Downloads.", "neutral"),
])
def test_classify(text, name):
    got, strength = emotion.classify(text)
    assert got == name and 0.0 <= strength <= 1.0
    assert (strength == 0.0) == (name == "neutral")


def test_resolve_uses_the_tag_first_and_maps_annoyed_to_the_avatars_angry():
    assert emotion.resolve("Whatever.", "annoyed") == ("angry", 0.5)
    assert emotion.resolve("Whatever.", "angry") == ("angry", 0.9)
    assert emotion.resolve("Sorry about that.", None)[0] == "sad"
    assert emotion.resolve("Sorry about that.", "happy")[0] == "happy"
    assert emotion.resolve("Fine.", None) == ("neutral", 0.0)


class StreamLLM:
    def __init__(self, reply):
        self.reply = reply

    def stream_json(self, system, user, schema, **kw):
        text = json.dumps({"reply": self.reply})
        for i in range(0, len(text), 5):
            yield text[i:i + 5]

    def complete_json(self, system, user, schema, **kw):
        return json.dumps({"reply": self.reply})


class Spoken:
    cancelled = False

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)


def collect():
    seen = []
    events.on("emotion", lambda name, strength: seen.append((name, strength)))
    return seen


def test_a_streamed_reply_emits_the_tagged_feeling_and_speaks_without_the_tag():
    seen, stream = collect(), Spoken()
    with sp.speaking_to(stream):
        text = Chat(StreamLLM("[annoyed] Oh, so now you remember me. What do you need?")).reply("hello?")
    assert stream.said == ["Oh, so now you remember me.", "What do you need?"]
    assert text == "Oh, so now you remember me. What do you need?" and "[" not in text
    assert seen == [("angry", 0.5)]


def test_without_a_tag_the_guess_is_used():
    seen, stream = collect(), Spoken()
    with sp.speaking_to(stream):
        Chat(StreamLLM("Oof, sorry. Want to talk about it?")).reply("rough day")
    assert seen == [("sad", 0.7)]


def test_a_later_sentence_with_its_own_tag_changes_the_feeling():
    seen = collect()
    with sp.speaking_to(Spoken()):
        Chat(StreamLLM("[sad] Oh no, that sounds really hard. [happy] But hey, tomorrow is another day.")).reply("bad day")
    assert seen == [("sad", 0.7), ("happy", 0.7)]


def test_the_tag_survives_a_dropped_first_sentence():
    seen, stream = collect(), Spoken()
    with sp.speaking_to(stream):
        Chat(StreamLLM("[happy] Just waiting by my terminal. Not much, you?")).reply("what's up")
    assert stream.said == ["Not much, you?"] and seen == [("happy", 0.7)]


def test_typed_chat_emits_too_and_strips_the_tag():
    seen = collect()
    text = Chat(StreamLLM("[shy] Oops, my bad.")).reply("you messed up")   # no stream: the plain path
    assert text == "Oops, my bad." and seen == [("shy", 0.6)]


def test_the_prompt_asks_for_a_feeling_only_when_there_is_a_companion(tmp_path):
    from red import companions
    assert "how you feel" not in Chat(None).system()
    system = Chat(None, persona=lambda: companions.load("red", tmp_path)).system()
    assert "Start every reply with how you feel, in brackets" in system
