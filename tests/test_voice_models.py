"""Real Whisper, Piper and openWakeWord models, without a microphone or speakers.

Piper's speech is fed straight into Whisper and the wake word detector.
Whisper runs on the CPU (int8) so it never competes with the LLM for VRAM.
Needs the models (python -m red.voice_demo --setup), so it only runs with
RED_INTEGRATION=1.
"""

import os
import re

import numpy as np
import pytest

from red.audio import SAMPLE_RATE, Endpointer, record_command, resample, to_int16
from red.config import red_home
from red.listener import WakeWordDetector
from red.stt import Transcriber
from red.tts import Speaker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("RED_INTEGRATION") != "1",
                       reason="set RED_INTEGRATION=1 to run"),
]

MODELS = red_home() / "models"


class Silent:
    def play(self, audio, rate): pass
    def wait(self): pass
    def stop(self): pass


@pytest.fixture(scope="module")
def speaker():
    return Speaker(MODELS / "piper", player=Silent())


@pytest.fixture(scope="module")
def transcriber():
    t = Transcriber(MODELS / "whisper", "small", device="cpu")
    t.load()
    return t


def speech(speaker, text, pad=0.5):
    audio, rate = speaker.synthesize(text)
    audio = resample(audio, rate)
    gap = np.zeros(int(pad * SAMPLE_RATE), np.float32)
    return np.concatenate([gap, audio, gap])


def words(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).split()


@pytest.mark.parametrize("text", [
    "Open my downloads folder.",
    "Shut down the computer in two hours.",
    "Yes.",
    "No.",
])
def test_piper_to_whisper_round_trip(speaker, transcriber, text):
    heard = transcriber.transcribe(speech(speaker, text))
    assert transcriber.device == "cpu" and transcriber.compute_type == "int8"
    assert words(heard) == words(text), heard


def test_endpointer_finds_real_speech(speaker):
    audio = speech(speaker, "Open the music folder.", pad=1.0)
    ep = Endpointer()
    for i in range(0, audio.size, 480):
        if ep.feed(audio[i:i + 480]):
            break
    assert ep.started
    assert 0 < ep.audio().size < audio.size


def test_record_then_transcribe_like_the_demo(speaker, transcriber):
    from voice_fakes import FakeMic, noise

    mic = FakeMic(np.zeros(4800, np.float32), noise(0.5), speech(speaker, "Play some music.", pad=0.2))
    audio = record_command(mic=mic)
    assert mic.seconds_read < 5
    assert words(transcriber.transcribe(audio)) == ["play", "some", "music"]


def test_wakeword_fires_on_the_phrase_only(speaker):
    det = WakeWordDetector(MODELS / "wakeword", "hey_jarvis")

    def peak(text):
        det.reset()
        audio = to_int16(np.concatenate([speech(speaker, text, pad=1.0),
                                         np.zeros(SAMPLE_RATE, np.float32)]))
        return max(det.score(audio[i:i + 1280]) for i in range(0, audio.size - 1279, 1280))

    assert peak("Hey Jarvis.") > 0.5
    assert peak("Open my downloads folder.") < 0.5
