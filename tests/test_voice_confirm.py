import inspect

import numpy as np
import pytest

from red.voice_confirm import ANSWER_SECONDS, speakable, spoken_ask
from voice_fakes import tone


class FakeSpeaker:
    def __init__(self, log):
        self.log = log

    def say(self, text, block=True):
        self.log.append(("say", text, block))


class FakeTranscriber:
    def __init__(self, log, text):
        self.log, self.text = log, text

    def transcribe(self, audio):
        self.log.append(("transcribe", audio.size))
        return self.text


class FakeListener:
    def __init__(self, log):
        self.log = log

    def pause(self):
        self.log.append("pause")

    def resume(self):
        self.log.append("resume")


def make(text="Yes.", audio=None, listener=False):
    log = []
    recorded = []

    def record(**kwargs):
        recorded.append(kwargs)
        log.append("record")
        return tone(0.5) if audio is None else audio

    ask = spoken_ask(FakeSpeaker(log), FakeTranscriber(log, text), record=record,
                     listener=FakeListener(log) if listener else None)
    return ask, log, recorded


@pytest.mark.parametrize("question, spoken", [
    ("Shut down in 2 hours (at 11:40 PM)? [y/N]", "Shut down in 2 hours (at 11:40 PM)? Say yes to confirm."),
    ("Restart now (y/n)", "Restart now? Say yes to confirm."),
    ("Delete it?", "Delete it? Say yes to confirm."),
    ("[y/N]", "Say yes to confirm."),
])
def test_speakable(question, spoken):
    assert speakable(question) == spoken


def test_speaks_then_records_then_returns_transcript():
    ask, log, recorded = make("Yes.")
    assert ask("Shut down in 2 hours? [y/N]", 30.0) == "Yes."
    assert log[0] == ("say", "Shut down in 2 hours? Say yes to confirm.", True)   # finishes speaking first
    assert log[1] == "record"
    assert log[2][0] == "transcribe"
    assert recorded == [{"max_seconds": 30.0 + ANSWER_SECONDS, "silence_seconds": 0.7,
                         "start_timeout": 30.0}]


def test_silence_is_a_timeout():
    ask, log, _ = make(audio=np.zeros(0, np.float32))
    assert ask("Restart?", 30.0) is None
    assert not any(isinstance(e, tuple) and e[0] == "transcribe" for e in log)


def test_empty_transcript_is_a_timeout():
    ask, _, _ = make(text="   ")
    assert ask("Restart?", 5.0) is None


def test_other_answers_are_passed_through_unchanged():
    # Deciding yes or no is confirm.is_yes's job, not spoken_ask's.
    ask, _, _ = make(text="No, cancel that.")
    assert ask("Restart?", 5.0) == "No, cancel that."


def test_listener_is_paused_around_the_question():
    ask, log, _ = make(listener=True)
    ask("Restart?", 5.0)
    assert log[0] == "pause" and log[-1] == "resume"


def test_matches_the_ask_signature():
    ask, _, _ = make()
    params = list(inspect.signature(ask).parameters)
    assert params == ["question", "timeout"]
