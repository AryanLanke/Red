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
    ("Hey Red, stop.", 1.0),           # a comma after "Hey Red": a command follows
    ("Hey Red. Open YouTube.", 1.0),
    ("Hey Red Light", 0.45),           # no comma: maybe a misheard "a red light", below 0.5
    ("Hey red one two", 0.45),
    ("Hi Red", 0.7),
    ("Ey Red", 0.7),
    ("Heyy Red", 0.7),
    ("Hey, read.", 0.6),
])
def test_wake_phrase_variants(text, expected):
    assert match_score(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "", "Red", "Hey", "Hey there", "Hey, Fred.", "Hey, ready to go?", "I read the red book.",
    "He read it yesterday.", "They said red.", "The red car is fast.", "A red car",
    "Hey computer", "Hey red one two three four",
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


def test_long_speech_only_has_its_start_checked_once():
    det, _, whisper = make("They said red.")
    assert max(run(det, noise(0.5), tone(5.0), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1 and whisper.clips[0] < 2.0     # the first 1.3 s, not 5 s


def test_hey_red_said_in_one_breath_with_a_command_wakes():
    # "Hey Red, open YouTube": 3 s of speech after a pause.
    det, _, whisper = make("Hey Red, open")
    scores = run(det, noise(1.0), tone(3.0), noise(1.0))
    assert max(scores) == 1.0 and len(whisper.clips) == 1


def test_a_long_sentence_that_does_not_start_with_hey_red_stays_asleep():
    det, _, _ = make("I saw a red car, hey red light")
    assert max(run(det, noise(1.0), tone(3.0), noise(1.0))) == 0.0


# What Whisper really wrote in the 2026-11-09 voice test (red.log) when the user said "Hey Red".
@pytest.mark.parametrize("heard", [
    "Hey Red Red Red Red Red Red Red", "Hey Red, hey Red, hey Red", "Hey Red, hey Red",
    "Hey Red Red", "hey red hey red hey red hey red",
])
def test_repeated_phrases_still_wake(heard):
    assert match_score(heard) == 1.0


@pytest.mark.parametrize("heard", ["Not waking up", "It's okay", "What is?", "Song by Liz Adafim",
                                   "Two Satora Lamb", "Red red red", "Invite this was happening"])
def test_the_other_things_heard_in_that_test_stay_asleep(heard):
    assert match_score(heard) < 0.5


def test_head_mode_looks_only_at_the_first_two_words():
    assert match_score("Hey Red, open YouTube and search", head=True) == 1.0
    assert match_score("I said hey red", head=True) == 0.0
    assert match_score("Hey Red open YouTube and search") < 0.5


# Short "Hey Red, <words>" clips from red.log that scored 0.45 or 0.32 and so never woke Red.
@pytest.mark.parametrize("heard, expected", [
    ("Hey Red, don't know", 1.0),
    ("Hey Red, don't walk", 1.0),
    ("Hi Red, what's up?", 0.7),
    ("Hey Red, what's the weather like today?", 1.0),
])
def test_hey_red_with_a_command_in_one_breath_wakes(heard, expected):
    assert match_score(heard) == pytest.approx(expected)


@pytest.mark.parametrize("heard", ["I read, the red book", "They said red, then left", "Hey, Fred, come here",
                                   "A red light, then green", "Hey there, red car"])
def test_a_comma_alone_does_not_make_a_wake_phrase(heard):
    assert match_score(heard) < 0.5


def test_too_short_bursts_are_skipped():
    det, _, whisper = make()
    run(det, noise(1.0), tone(0.15), noise(1.0))
    assert whisper.clips == []


def test_phrase_run_into_previous_speech_is_skipped():
    # Speech, a gap shorter than the pause needed, then a short burst: mid-conversation.
    det, _, whisper = make()
    run(det, noise(0.5), tone(2.5), noise(0.1), tone(0.6), noise(1.0))
    assert len(whisper.clips) == 1                         # the start of the long burst, nothing else


def test_conversation_with_pauses_checks_only_short_isolated_bursts():
    det, _, whisper = make("Something else.")
    pieces = [noise(0.5)]
    for length in (2.5, 0.8, 3.0, 1.9, 0.6, 4.0):
        pieces += [tone(length), noise(0.5)]
    run(det, *pieces)
    # The 0.8 s and 0.6 s bursts, and the first 1.3 s of each of the four long ones (cheap, once each).
    assert len(whisper.clips) == 6 and max(whisper.clips) < 2.0


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


# Every burst that never reaches Whisper says why in red.log (plan.md task 1.2).

def skips(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Wake skip:")]


def test_a_too_short_burst_logs_why(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, _ = make()
    run(det, noise(1.0), tone(0.15), noise(1.0))
    assert len(skips(caplog)) == 1 and "too short" in skips(caplog)[0]


def test_a_phrase_run_into_earlier_speech_is_one_burst_whose_start_is_checked(caplog):
    # A burst only ends after PAUSE_AFTER (0.3 s) of quiet, which is already more than
    # PAUSE_BEFORE (0.25 s): a "Hey Red" with a shorter gap before it merges into the earlier
    # speech, and only the start of that merged burst (the earlier speech) is checked.
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, whisper = make("Something else, hey red")
    assert max(run(det, noise(0.5), tone(0.8), noise(0.1), tone(0.9), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1
    assert any("start of a longer phrase" in r.getMessage() for r in caplog.records)


class FaintVAD(LoudnessVAD):
    """Speech the VAD is unsure of: above the 'too faint' line, below the start of a clip."""

    def __call__(self, chunk):
        return 0.4 if super().__call__(chunk) > 0.5 else 0.05


def test_speech_too_faint_to_start_a_clip_logs_why(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    whisper = FakeWhisper()
    det = HeyRedDetector(FaintVAD(), whisper)
    run(det, noise(1.0), tone(0.7), noise(1.0))
    assert whisper.clips == []
    assert len(skips(caplog)) == 1 and "too faint" in skips(caplog)[0] and "VAD 0.40" in skips(caplog)[0]


def test_a_checked_phrase_logs_no_skip(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, _ = make()
    run(det, noise(1.0), tone(0.7), noise(1.0))
    assert skips(caplog) == []
