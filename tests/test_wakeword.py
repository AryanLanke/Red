import numpy as np
import pytest

from red.audio import SAMPLE_RATE, to_int16
from red.wakeword import HeyRedDetector, match_score
from voice_fakes import noise, tone


@pytest.mark.parametrize("text, expected", [
    ("Hey Red", 1.0),
    ("Hey, Red!", 1.0),
    ("hey red.", 1.0),
    ("Hay Red", 1.0),
    ("Heyred", 0.9),
    ("Hey Red, stop.", 0.45),          # below the default threshold of 0.5
    ("Hey Red Light", 0.45),
    ("Hi Red", 0.7),
    ("Hey, read.", 0.6),
])
def test_wake_phrase_variants(text, expected):
    assert match_score(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "", "Red", "Hey", "Hey there", "Hey, Fred.", "Hey, ready to go?", "I read the red book.",
    "He read it yesterday.", "They said red.", "The red car is fast.", "A red car",
    "Hey Jarvis", "Hey red one two three four",
])
def test_ordinary_speech_does_not_match(text):
    assert match_score(text) < 0.5


class LoudnessVAD:
    """Fake VAD: anything louder than quiet noise is speech."""

    def __init__(self):
        self.calls = 0
        self.resets = 0

    def __call__(self, chunk):
        self.calls += 1
        assert chunk.size == 512 and chunk.dtype == np.float32
        return 0.9 if np.sqrt(np.mean(chunk ** 2)) > 0.02 else 0.05

    def reset(self):
        self.resets += 1


class FakeWhisper:
    def __init__(self, text="Hey Red."):
        self.text = text
        self.clips = []

    def __call__(self, clip):
        self.clips.append(clip.size / SAMPLE_RATE)
        return self.text


def run(det, *pieces, frame=1280):
    audio = to_int16(np.concatenate(pieces))
    return [det.score(audio[i:i + frame]) for i in range(0, audio.size, frame)]


def make(text="Hey Red."):
    vad, whisper = LoudnessVAD(), FakeWhisper(text)
    return HeyRedDetector(vad, whisper), vad, whisper


def test_short_phrase_between_pauses_is_checked_and_fires():
    det, _, whisper = make()
    scores = run(det, noise(1.0), tone(0.7), noise(1.0))
    assert max(scores) == 1.0
    assert whisper.clips and 0.9 < whisper.clips[0] < 1.6   # phrase + pre-roll + pause
    fired = int(np.argmax(scores)) * 1280 / SAMPLE_RATE
    assert 1.7 < fired < 2.3                                # just after the pause that ends it


def test_fires_once_per_phrase():
    det, _, whisper = make()
    scores = run(det, noise(1.0), tone(0.7), noise(2.0))
    assert sum(s >= 0.5 for s in scores) == 1
    assert len(whisper.clips) == 1


def test_ordinary_words_do_not_fire():
    det, _, whisper = make("They said red.")
    assert max(run(det, noise(1.0), tone(0.8), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1


def test_long_speech_is_never_sent_to_whisper():
    det, _, whisper = make()
    assert max(run(det, noise(0.5), tone(5.0), noise(1.0))) == 0.0
    assert whisper.clips == []


def test_too_short_bursts_are_skipped():
    det, _, whisper = make()
    run(det, noise(1.0), tone(0.15), noise(1.0))
    assert whisper.clips == []


def test_phrase_run_into_previous_speech_is_skipped():
    # Speech, a gap shorter than the pause needed, then a short burst: mid-conversation.
    det, _, whisper = make()
    run(det, noise(0.5), tone(2.5), noise(0.1), tone(0.6), noise(1.0))
    assert whisper.clips == []


def test_conversation_with_pauses_checks_only_short_isolated_bursts():
    det, _, whisper = make("Something else.")
    pieces = [noise(0.5)]
    for length in (2.5, 0.8, 3.0, 1.9, 0.6, 4.0):
        pieces += [tone(length), noise(0.5)]
    run(det, *pieces)
    assert len(whisper.clips) == 2                          # only the 0.8 s and 0.6 s bursts


def test_works_with_odd_frame_sizes_and_float_input():
    det, vad, _ = make()
    audio = np.concatenate([noise(1.0), tone(0.7), noise(1.0)])
    scores = [det.score(audio[i:i + 777]) for i in range(0, audio.size, 777)]
    assert max(scores) == 1.0
    assert vad.calls == audio.size // 512


def test_reset_drops_a_half_heard_phrase():
    det, vad, whisper = make()
    run(det, noise(1.0), tone(0.4))
    det.reset()
    assert vad.resets >= 2
    run(det, noise(1.0))
    assert whisper.clips == []


def test_counts_whisper_time():
    ticks = iter([0.0, 0.25, 1.0, 1.3])
    det = HeyRedDetector(LoudnessVAD(), FakeWhisper(), clock=lambda: next(ticks))
    run(det, noise(1.0), tone(0.7), noise(1.0), tone(0.7), noise(1.0))
    assert det.evaluations == 2
    assert det.busy_seconds == pytest.approx(0.55)
    assert det.last_text == "Hey Red."
