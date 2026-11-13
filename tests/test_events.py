"""red/events.py and the events the voice loop emits (plan.md 0.2)."""

import threading

import numpy as np
import pytest

from red import events
from red.speech import SpeechStream


@pytest.fixture(autouse=True)
def clean():
    events.clear()
    yield
    events.clear()


def test_on_emit_off():
    got = []
    remove = events.on("said", lambda text: got.append(text))
    events.emit("said", text="hi")
    remove()
    events.emit("said", text="again")
    assert got == ["hi"]


def test_a_failing_handler_never_reaches_the_emitter_or_the_others():
    got = []
    events.on("heard", lambda text: 1 / 0)
    events.on("heard", lambda text: got.append(text))
    events.emit("heard", text="open YouTube")           # no exception
    assert got == ["open YouTube"]


def test_a_payload_may_have_a_name():
    got = []
    events.on("state", lambda name, text: got.append((name, text)))
    events.emit("state", name="speaking", text="Hi.")
    assert got == [("speaking", "Hi.")]


def test_no_handlers_is_fine():
    events.emit("nobody-listens", x=1)


def test_thread_safe_registration():
    got = []
    threads = [threading.Thread(target=lambda: events.on("x", lambda: got.append(1))) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events.emit("x")
    assert len(got) == 20


class Player:
    def __init__(self, log):
        self.log = log

    def play(self, audio, rate):
        self.log.append(("play", int(audio[0])))

    def wait(self):
        pass


class Speaker:
    using_fallback = True

    def __init__(self, log):
        self.log, self.n = log, 0
        self.player = Player(log)

    def synthesize(self, text):
        self.n += 1
        return np.full(10, self.n, dtype=np.float32), 24000

    def stop(self):
        pass


def test_said_fires_when_the_audio_starts_not_when_written():
    log = []
    events.on("said", lambda text: log.append(("said", text)))
    stream = SpeechStream(Speaker(log), sleep=lambda s: None)
    stream.say("Not much.")
    stream.say("You?")
    stream.finish(timeout=5)
    # each piece is revealed right after its audio starts, never ahead of it
    assert log == [("play", 1), ("said", "Not much."), ("play", 2), ("said", "You?")]
