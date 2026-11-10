"""Debate and back-and-forth mode (red.chat): starting it, keeping it going, and ending it."""

import json
from datetime import datetime

import pytest

from red import speech as sp
from red.chat import (CHAT_SYSTEM, DEBATE_SYSTEM, YOUR_TURN, Chat, debate_topic_from,
                      with_your_turn)

NOW = datetime(2026, 11, 10, 20, 15)


class DebateLLM:
    def __init__(self, *replies, fail=False):
        self.replies = list(replies)
        self.calls = []
        self.fail = fail

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user, kw))
        if self.fail:
            raise OSError("model down")
        return json.dumps({"reply": self.replies.pop(0)})


class StreamLLM(DebateLLM):
    def stream_json(self, system, user, schema, **kw):
        self.calls.append((system, user, kw))
        text = self.replies.pop(0)
        raw = json.dumps({"reply": text})
        for i in range(0, len(raw), 8):
            yield raw[i:i + 8]


class Speaker:
    def __init__(self):
        self.said = []

    def say(self, text, block=True):
        self.said.append(text)


# --- topics and "Your turn." -------------------------------------------------------

@pytest.mark.parametrize("said, topic", [
    ("let's have a debate about AI regulation", "AI regulation"),
    ("Let's debate pineapple on pizza", "pineapple on pizza"),
    ("debate about tabs versus spaces", "tabs versus spaces"),
    ("argue about whether it's better to be early", "whether it's better to be early"),
    ("let's discuss AI safety", "AI safety"),
    ("quiz me on capitals", "capitals"),
    ("quiz me about the solar system", "the solar system"),
    ("let's have a debate", ""),
    ("I'm feeling chatty", ""),
])
def test_debate_topic_from(said, topic):
    assert debate_topic_from(said) == topic


@pytest.mark.parametrize("text, said", [
    ("One. Two.", "One. Two. Your turn."),
    ("One. Two. Your turn.", "One. Two. Your turn."),
    ("One. Two. Your turn", "One. Two. Your turn."),
    ("", "Your turn."),
])
def test_with_your_turn(text, said):
    assert with_your_turn(text) == said


# --- starting a debate -------------------------------------------------------------

def test_a_debate_starts_and_asks_for_their_turn():
    llm = DebateLLM("AI writes the boring code. People keep the taste. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    reply = chat.reply("Let's have a debate about AI writing code")
    assert chat.is_debate and chat.debate_topic == "AI writing code"
    assert reply == "AI writes the boring code. People keep the taste. Your turn."
    system, prompt, kw = llm.calls[0]
    assert system == DEBATE_SYSTEM
    assert "The debate topic is: AI writing code." in prompt
    assert reply.endswith(YOUR_TURN)
    assert kw["temperature"] > 0


def test_a_debate_with_no_topic_lets_red_pick_one():
    llm = DebateLLM("Okay: tea over coffee, every time. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Let's have a debate")
    assert chat.is_debate and chat.debate_topic == ""
    prompt = llm.calls[0][1]
    assert "pick a fun, everyday one" in prompt


def test_quiz_me_starts_a_quiz():
    llm = DebateLLM("First question: what's the capital of Peru? Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    assert chat.reply("Quiz me on capitals").endswith(YOUR_TURN)
    assert chat.is_debate and chat.debate_topic == "capitals"
    assert llm.calls[0][0] == DEBATE_SYSTEM


def test_a_debate_reply_missing_your_turn_gets_it():
    llm = DebateLLM("Pineapple belongs on pizza. Sweet meets salty.")
    chat = Chat(llm, now=lambda: NOW)
    assert chat.reply("debate about pineapple on pizza") == \
        "Pineapple belongs on pizza. Sweet meets salty. Your turn."


# --- keeping it going --------------------------------------------------------------

def test_each_turn_has_the_history_and_still_wants_a_reply():
    llm = DebateLLM("Cities need the tax money. Your turn.", "But farms feed the cities. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Let's debate about taxes")
    reply = chat.reply("Farms are the real economy though.")
    assert chat.is_debate
    assert reply.endswith(YOUR_TURN)
    system, prompt, _ = llm.calls[1]
    assert system == DEBATE_SYSTEM
    assert "The debate topic is: taxes." in prompt
    assert "User: Let's debate about taxes" in prompt
    assert "Red: Cities need the tax money. Your turn." in prompt
    assert "The user now says: Farms are the real economy though.\n\n(Keep it going:" in prompt


def test_a_new_command_does_not_start_a_debate():
    llm = DebateLLM("Nice.")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Open YouTube")
    assert not chat.is_debate
    assert llm.calls[0][0] == CHAT_SYSTEM
    assert "Your turn." not in llm.calls[0][1]


def test_a_debate_forgets_itself_after_a_quiet_spell():
    t = [0.0]
    llm = DebateLLM("Yes?")
    chat = Chat(llm, clock=lambda: t[0], forget_after=60, now=lambda: NOW)
    chat.reply("Let's debate about mornings")
    assert chat.is_debate
    t[0] = 61
    chat.reply("Anyway, what's up?")
    assert not chat.is_debate and chat.debate_topic == ""
    assert llm.calls[-1][0] == CHAT_SYSTEM


# --- ending it ---------------------------------------------------------------------

@pytest.mark.parametrize("said, reply", [
    ("stop", "Fair enough. Good debate."),
    ("Stop it.", "Fair enough. Good debate."),
    ("okay, enough", "Fair enough. Good debate."),
    ("no more", "Fair enough. Good debate."),
    ("you win", "You win. Good debate."),
    ("Okay, you win.", "You win. Good debate."),
    ("I give up", "You win. Good debate."),
    ("fine, I concede", "You win. Good debate."),
    ("end the debate", "Fair enough. Good debate."),
    ("that's enough", "Fair enough. Good debate."),
])
def test_debate_ends_without_bothering_the_model(said, reply):
    llm = DebateLLM("AI is fine. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Let's debate about AI")
    calls = len(llm.calls)
    assert chat.reply(said) == reply
    assert len(llm.calls) == calls                 # never asked the model
    assert not chat.is_debate and chat.debate_topic == ""
    assert chat.turns[-2] == ("User", said)        # still remembered
    assert chat.turns[-1] == ("Red", reply)


def test_stop_in_the_middle_of_something_else_is_not_the_end():
    llm = DebateLLM("Fine. Your turn.", "Sure. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Let's debate about AI")
    reply = chat.reply("stop watching VS Code")
    assert chat.is_debate
    assert reply.endswith(YOUR_TURN)
    assert len(llm.calls) == 2


def test_you_win_outside_a_debate_is_just_chat():
    llm = DebateLLM("Ha, that was quick.")
    chat = Chat(llm, now=lambda: NOW)
    assert chat.reply("you win") == "Ha, that was quick."
    assert len(llm.calls) == 1 and llm.calls[0][0] == CHAT_SYSTEM


def test_leaving_a_debate_with_a_goodbye_still_works():
    # "bye" isn't a debate exit here; red.__main__ ends the debate on a goodbye.
    llm = DebateLLM("Fair point. Your turn.", "Later!")
    chat = Chat(llm, now=lambda: NOW)
    chat.reply("Let's debate about AI")
    chat.end_debate()
    assert chat.reply("bye") == "Later!"
    assert not chat.is_debate


# --- streaming (the voice loop) ----------------------------------------------------

def test_a_streamed_debate_turn_speaks_your_turn():
    llm = StreamLLM("Short version: city life wins. Your turn.")
    chat = Chat(llm, now=lambda: NOW)
    speaker, stream = Speaker(), None
    stream = sp.SpeechStream(speaker)
    with sp.speaking_to(stream):
        reply = chat.reply("Let's debate about city versus country")
    stream.finish(timeout=5)
    assert chat.is_debate
    assert stream.spoken[-1] == YOUR_TURN
    assert reply.endswith(YOUR_TURN)


def test_a_streamed_debate_that_forgot_your_turn_still_says_it():
    llm = StreamLLM("City life wins on jobs and food.")
    chat = Chat(llm, now=lambda: NOW)
    stream = sp.SpeechStream(Speaker())
    with sp.speaking_to(stream):
        reply = chat.reply("Let's debate about city versus country")
    stream.finish(timeout=5)
    assert stream.spoken == ["City life wins on jobs and food.", YOUR_TURN]
    assert reply == "City life wins on jobs and food. Your turn."


def test_a_streamed_normal_chat_never_says_your_turn():
    llm = StreamLLM("Not bad. You?")
    chat = Chat(llm, now=lambda: NOW)
    stream = sp.SpeechStream(Speaker())
    with sp.speaking_to(stream):
        chat.reply("How's it going?")
    stream.finish(timeout=5)
    assert YOUR_TURN not in " ".join(stream.spoken)


def test_the_model_failing_leaves_the_debate_alive():
    chat = Chat(DebateLLM(fail=True), now=lambda: NOW)
    assert chat.reply("Let's debate about AI", fallback="Hm, say that again?") == \
        "Hm, say that again?"
    assert chat.is_debate                     # try again on the next turn
