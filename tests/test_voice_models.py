"""Real Whisper, Piper and wake word models, without a microphone or speakers.

Piper's speech is fed straight into Whisper and the wake word detector.
Whisper runs on the CPU (int8) so it never competes with the LLM for VRAM.
Needs the models (python -m red setup), so it only runs with
RED_INTEGRATION=1.
"""

import os
import re

import numpy as np
import pytest

from red.audio import SAMPLE_RATE, Endpointer, record_command, resample, to_int16
from red.config import red_home
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


# --- "Hey Red" ------------------------------------------------------------------

VOICES = ["en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-medium", "en_US-joe-medium",
          "en_GB-alan-medium", "en_GB-jenny_dioco-medium"]
MANY_SPEAKERS = "en_US-libritts_r-medium"

# Ordinary speech, including words close to the phrase. Each is said on its
# own with pauses around it, which is exactly what the detector checks.
ORDINARY = ["I read the red book.", "He read it yesterday.", "Hey, ready to go?", "They said red.",
            "Hey, Fred.", "Hey there.", "The red car is fast.", "Red is my favourite colour.",
            "Hey, how are you?", "Read it again.", "A red light.", "Thank you.", "Hey, Ted!",
            "Bread.", "Hey Rex.", "Hey, Rick."]


@pytest.fixture(scope="module")
def voice():
    from piper import PiperVoice, SynthesisConfig
    loaded = {}

    def say(name, text, speaker_id=None, speed=1.0):
        if name not in loaded:
            path = Speaker(MODELS / "piper", name, player=Silent()).download()
            loaded[name] = PiperVoice.load(path)
        chunks = list(loaded[name].synthesize(
            text, SynthesisConfig(speaker_id=speaker_id, length_scale=1.0 / speed)))
        audio = np.concatenate([c.audio_float_array for c in chunks])
        return resample(audio, chunks[0].sample_rate) * 0.5

    return say


@pytest.fixture(scope="module")
def hey_red():
    from red.listener import make_detector
    return make_detector(MODELS / "wakeword", "hey_red")


def room(seconds, rng=np.random.default_rng(0)):
    return (0.003 * rng.standard_normal(int(seconds * SAMPLE_RATE))).astype(np.float32)


def peak(detector, audio):
    detector.reset()
    x = to_int16(np.concatenate([room(1.0), audio + room(audio.size / SAMPLE_RATE), room(1.0)]))
    return max(detector.score(x[i:i + 1280]) for i in range(0, x.size, 1280))


@pytest.mark.parametrize("name", VOICES)
@pytest.mark.parametrize("speed", [0.8, 1.0, 1.25])
def test_hey_red_triggers(hey_red, voice, name, speed):
    for text in ("Hey Red.", "Hey, Red!"):
        assert peak(hey_red, voice(name, text, speed=speed)) >= 0.5, (name, speed, text, hey_red.last_text)


@pytest.mark.parametrize("speaker_id", [5, 150, 300, 500, 700, 850])
def test_hey_red_triggers_for_many_speakers(hey_red, voice, speaker_id):
    assert peak(hey_red, voice(MANY_SPEAKERS, "Hey Red.", speaker_id)) >= 0.5, hey_red.last_text


@pytest.mark.parametrize("name", VOICES)
def test_ordinary_speech_does_not_trigger(hey_red, voice, name):
    fired = [(t, hey_red.last_text) for t in ORDINARY if peak(hey_red, voice(name, t)) >= 0.5]
    assert fired == []


def test_conversation_does_not_trigger_and_stays_cheap(hey_red, voice):
    talk = ("So I was thinking we could go out later. Maybe around six? Sure. The red one looked "
            "nice, but I read the reviews first. Yeah. Hey, did you see that? It was great. "
            "Okay, see you then. Red or blue, I don't mind. Bye.")
    rng = np.random.default_rng(1)
    parts = []
    for sentence in talk.split(". "):
        parts += [voice("en_US-amy-medium", sentence), room(rng.uniform(0.2, 0.7))]
    audio = np.concatenate(parts)
    hey_red.reset()
    before_runs, before_busy = hey_red.evaluations, hey_red.busy_seconds
    x = to_int16(audio + room(audio.size / SAMPLE_RATE))
    assert max(hey_red.score(x[i:i + 1280]) for i in range(0, x.size, 1280)) < 0.5
    seconds = audio.size / SAMPLE_RATE
    busy = hey_red.busy_seconds - before_busy
    assert hey_red.evaluations - before_runs <= 6
    assert busy / seconds < 0.25                 # Whisper busy under a quarter of the time


def test_quiet_room_costs_almost_nothing(hey_red):
    import time
    hey_red.reset()
    x = to_int16(room(20.0))
    runs = hey_red.evaluations
    t0 = time.process_time()
    for i in range(0, x.size, 1280):
        hey_red.score(x[i:i + 1280])
    assert hey_red.evaluations == runs
    assert time.process_time() - t0 < 1.0        # under 5% of one core
