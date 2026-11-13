"""red/gate.py: plain talk skips the router; anything that might be a command doesn't."""

import pytest

from red.gate import needs_router

# The user's own words from 2026-11-13 (logs/commands.jsonl) that the router sent to chat.
TALK = [
    "What's up?", "Hey Red, what's up?", "What's up, man?", "What's up man, how you doing?",
    "How are you?", "how you doin?", "It's good, what about you?", "It's going good. Thanks.",
    "What is going on in your mind right now?", "what's going on in your mind right now.",
    "What's going on your mind right now?", "So, what is going in your mind right now?",
    "What are you doing right now?", "Are you chilling right now?", "Are you listening to me?",
    "Don't sleep, OK?", "You're crazy.", "You're a nerd.", "You're sort of offensive.",
    "You really make me angry.", "I'm feeling lonely.", "I'm not talking to you.",
    "I'm saying that are you mad?", "I heard you before. Aren't you mad at me for that?",
    "I don't like the way you talk", "Man, I just wanna sleep.", "I already woke up man",
    "True, I love retro gadgets", "No man, I think", "A lot for me", "Hit it.", "Here we go.",
    "I really feel like to laugh and just laugh with me.", "Think you have good luck, OK?",
    "I'm sorry for what I said earlier, honestly. I'm really sorry. I just want you to be with me. "
    "Will you be with me?",
    "Because I don't feel sleepy, I wanna do work. What about you?",
    "I don't know what should I do, what do you feel I should do?",
]

# Commands and questions about the world: these must still go to the router.
ROUTED = [
    "Open YouTube", "Open edge.", "Can you open YouTube for me from Chrome?",
    "Red you just open chrome. I told you to open YouTube", "Play Crazy by Alexa Raffy",
    "play music by Justin Bieber", "Play any song of my favorite", "Stop playing. Stop playing the music.",
    "Turn off my PC after 4 hour", "I'll tell you to turn off my laptop after 3 hours, will you do that?",
    "When the code finishes, when my VS code says finished, just wait, just remind me, OK?",
    "Call me Arian, it is spelled as A R Y A M.", "These are even, it's spelled as A-R-Y-A-N",
    "What's on my screen right now", "Do you see my screen?", "Can you see what's on my screen?",
    "what is Hugging Face", "What's the latest iPhone?", "who made Siri", "how tall is mount everest",
    "compare Siri with Alexa", "explain recursion", "What's Punisher about?", "Do you know Punisher web series?",
    "Do you know when would that be launched in India?", "What is Hey CD?",
    "set a timer for 5 minutes", "what's the weather", "mute", "lock the PC", "volume up",
    "remind me to drink water at 5", "find the folder named taxes", "open downloads",
    "let's have a debate", "quiz me on history", "is my name", "check my repos", "read my mail",
    "what time is it in Tokyo", "who won the match yesterday",
]


@pytest.mark.parametrize("text", TALK)
def test_talk_goes_straight_to_chat(text):
    assert not needs_router(text)


@pytest.mark.parametrize("text", ROUTED)
def test_commands_and_facts_are_routed(text):
    assert needs_router(text)


def test_empty_is_routed():
    assert needs_router("")
    assert needs_router("  ...  ")


def test_talk_about_us_with_a_command_is_routed():
    assert needs_router("how are you, and open YouTube")
    assert needs_router("I'm bored, play some music")
    assert needs_router("you're crazy, turn off the PC")


def test_talk_only_needs_the_setting_and_no_tool_before():
    from types import SimpleNamespace

    from red.__main__ import talk_only
    on, off = SimpleNamespace(chat_first=True), SimpleNamespace(chat_first=False)
    assert talk_only("You're crazy.", None, on)
    assert talk_only("You're crazy.", "none", on)
    assert not talk_only("You're crazy.", None, off)
    # Right after a tool, an answer to it ("Blink Crazy by Lisa") goes to the router.
    assert not talk_only("Blink Crazy by Lisa Raffin", "play_online", on)
    assert not talk_only("open YouTube", None, on)


def test_talk_route_is_chat():
    from red.router import Router
    route = Router.talk_route()
    assert route.is_none and not route.destructive and route.args["reply"]
