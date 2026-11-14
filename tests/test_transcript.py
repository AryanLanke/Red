"""The clean-up of fillers and self-corrections (red/transcript.py), with no model."""

import json
import re
from pathlib import Path

import pytest

from red.transcript import clean_transcript

SENTENCES = json.loads((Path(__file__).parent / "fixtures" / "voice" / "sentences.json").read_text(encoding="utf-8"))


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


@pytest.mark.parametrize("item", SENTENCES, ids=[i["said"][:40] for i in SENTENCES])
def test_the_spoken_sentences_come_out_as_meant(item):
    assert words(clean_transcript(item["said"])) == words(item["meant"])


@pytest.mark.parametrize("heard, meant", [
    # What Whisper really wrote for those clips (numbers as digits, "weight" for "wait", ...).
    ("Open chrome, no weight, open edge.", "Open edge."),
    ("Set a timer for 5, I mean 10 minutes.", "Set a timer for 10 minutes."),
    ("Play something by Aragit Singh, No Sorry by Lisa.", "Play something by Lisa."),
    ("Remind me at 6, actually, make it 7.", "Remind me at 7."),
    ("Open the Downloads folder, I mean the Documents folder.", "Open the Documents folder."),
    ("Turn the volume up, no down.", "Turn the volume down."),
    ("Umm, uh, what was I saying? Oh yes, open Spotify.", "Open Spotify."),
    ("Search for flights to Goa. Wait to Mumbai.", "Search for flights to Mumbai."),
    ("open open Chrome", "Open Chrome"),
    ("I I want to go.", "I want to go."),
    ("Tell me the weather in Pune, no, in Delhi.", "Tell me the weather in Delhi."),
    ("Open the file in the editor, sorry, the terminal.", "Open the file in the terminal."),
    ("It's, like, really hard to say.", "It's really hard to say."),
])
def test_what_whisper_wrote_and_what_was_meant(heard, meant):
    assert clean_transcript(heard) == meant


@pytest.mark.parametrize("said", [
    "No, I don't want that.",
    "No no no",
    "I'm sorry, Dave.",
    "Yes.",
    "Is it a cat, no, it's a dog and it barks a lot.",       # a long "no" is an answer, not a correction
    "I like to play games like Minecraft.",
    "I mean business.",
    "Wait for me.",
    "Open YouTube and play lo-fi beats.",
    "Hey Red, open YouTube.",
    "mm-hmm",
])
def test_ordinary_talk_is_left_alone(said):
    assert clean_transcript(said) == said


@pytest.mark.parametrize("filler", ["um", "Hmm.", "uh...", "Um, uh.", "  "])
def test_nothing_is_made_of_a_bare_filler(filler):
    # The filler check downstream (smalltalk.is_filler) must still see it.
    assert clean_transcript(filler) == filler.strip()


def test_empty_and_none():
    assert clean_transcript("") == ""
    assert clean_transcript(None) == ""


def test_the_end_mark_is_kept():
    assert clean_transcript("Um, what time is it?") == "What time is it?"
    assert clean_transcript("um open edge") == "Open edge"


def test_i_mean_between_commas_is_still_a_correction():
    assert clean_transcript("Set a timer for five, I mean, ten minutes.") == "Set a timer for ten minutes."
