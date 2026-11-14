"""Making Red faster: the quick end of speech, and the timing line in red.log."""

import pytest

from red import __main__ as cli
from red.audio import SAMPLE_RATE, record_command
from red.config import load_settings
from red.smalltalk import sounds_finished
from voice_fakes import FakeMic, noise, tone


@pytest.mark.parametrize("text, done", [
    ("Open Edge.", True), ("open my downloads", True), ("What's the weather in Pune?", True),
    ("Play Punisher trailer", True),
    ("Open Edge and", False), ("Open Edge and...", False), ("um", False), ("Hmm.", False),
    ("Play the", False), ("Remind me to", False), ("Open Edge,", False), ("okay so", False),
    ("Can you", False), ("", False), ("   ", False),
])
def test_sounds_finished(text, done):
    assert sounds_finished(text) is done


class Checks:
    """is_complete() for record_command: answers in order, records how much audio it saw."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    def __call__(self, audio):
        self.seen.append(audio.size / SAMPLE_RATE)
        return self.answers.pop(0) if self.answers else False


def test_a_finished_sentence_ends_after_the_short_pause():
    mic = FakeMic(noise(0.5), tone(1.0), noise(3.0))
    check = Checks(True)
    out = record_command(silence_seconds=1.5, quick_silence=0.8, is_complete=check, mic=mic)
    assert len(check.seen) == 1
    # 1 s of speech + 0.3 s pre-roll + ~0.8 s of pause, not 1.5 s
    assert 1.9 < out.size / SAMPLE_RATE < 2.3
    assert check.seen[0] == out.size / SAMPLE_RATE      # the checked audio is what's returned


def test_an_unfinished_sentence_waits_the_full_pause():
    mic = FakeMic(noise(0.5), tone(1.0), noise(3.0))
    check = Checks(False)
    out = record_command(silence_seconds=1.5, quick_silence=0.8, is_complete=check, mic=mic)
    assert len(check.seen) == 1                          # one check per pause
    assert 2.6 < out.size / SAMPLE_RATE < 3.0


def test_each_pause_is_checked_once():
    # "open Edge and ... YouTube": unfinished at the first pause, finished at the second.
    mic = FakeMic(noise(0.5), tone(0.6), noise(1.0), tone(0.6), noise(3.0))
    check = Checks(False, True)
    out = record_command(silence_seconds=1.5, quick_silence=0.8, is_complete=check, mic=mic)
    assert len(check.seen) == 2
    assert out.size / SAMPLE_RATE > 3.0                  # both parts are in


def test_no_check_without_a_quick_pause():
    mic = FakeMic(noise(0.5), tone(1.0), noise(3.0))
    check = Checks(True)
    record_command(silence_seconds=1.5, quick_silence=0.0, is_complete=check, mic=mic)
    assert check.seen == []


# --- transcribing during the pause (night 1) ---------------------------------------

class SlowChecks(Checks):
    """Like Checks, but each check takes a moment, as Whisper does."""

    def __call__(self, audio):
        import time
        time.sleep(0.02)
        return super().__call__(audio)


class SlowMic(FakeMic):
    """A fake microphone that is only about 6 times faster than real time, so a thread can keep up."""

    def read(self, timeout: float = 2.0):
        import time
        time.sleep(0.005)
        return super().read(timeout)


def test_a_guess_made_during_the_pause_ends_it_at_the_short_pause():
    mic = SlowMic(noise(0.5), tone(1.0), noise(3.0))
    check = SlowChecks(True)
    stats = {}
    out = record_command(silence_seconds=1.5, quick_silence=0.5, speculate_after=0.15,
                         is_complete=check, mic=mic, stats=stats)
    assert len(check.seen) == 1
    assert check.seen[0] == out.size / SAMPLE_RATE      # the audio returned is the audio that was checked
    assert 1.4 < out.size / SAMPLE_RATE < 2.0           # 1 s speech + 0.3 s pre-roll + the quiet at the guess
    assert 0.5 <= stats["quiet"] < 0.9
    assert 0.15 <= stats["ready"] < 0.6                 # the text was ready well before the pause ended


def test_a_guess_is_dropped_when_you_carry_on_talking():
    # "open Edge ... and YouTube": the first guess is for a pause that did not end the sentence.
    mic = SlowMic(noise(0.5), tone(0.6), noise(0.3), tone(0.6), noise(3.0))
    check = SlowChecks(True, True)
    out = record_command(silence_seconds=1.5, quick_silence=0.5, speculate_after=0.15,
                         is_complete=check, mic=mic)
    assert out.size / SAMPLE_RATE > 1.7                  # both parts are in
    assert check.seen[-1] == out.size / SAMPLE_RATE      # the last check saw all of it


def test_an_unfinished_guess_waits_the_full_pause():
    mic = SlowMic(noise(0.5), tone(1.0), noise(3.0))
    check = SlowChecks(False)
    stats = {}
    out = record_command(silence_seconds=1.5, quick_silence=0.5, speculate_after=0.15,
                         is_complete=check, mic=mic, stats=stats)
    assert len(check.seen) == 1
    assert 2.6 < out.size / SAMPLE_RATE < 3.0
    assert "ready" not in stats and stats["quiet"] >= 1.5


def test_a_check_can_ask_for_a_longer_pause():
    # One or two words ("Hope.") get 0.8 s instead of 0.5 s.
    mic = SlowMic(noise(0.5), tone(0.5), noise(3.0))
    stats = {}
    record_command(silence_seconds=1.5, quick_silence=0.5, speculate_after=0.15,
                   is_complete=lambda audio: 0.8, mic=SlowMic(noise(0.5), tone(0.5), noise(3.0)), stats=stats)
    assert 0.8 <= stats["quiet"] < 1.2


def test_a_failing_guess_just_waits_the_full_pause():
    def broken(audio):
        raise RuntimeError("whisper crashed")
    mic = SlowMic(noise(0.5), tone(1.0), noise(3.0))
    out = record_command(silence_seconds=1.5, quick_silence=0.5, speculate_after=0.15,
                         is_complete=broken, mic=mic)
    assert 2.6 < out.size / SAMPLE_RATE < 3.0


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_timing_counts_from_the_end_of_speech(tmp_path, monkeypatch):
    for name in ("RED_END_SILENCE", "RED_QUICK_END_SILENCE"):
        monkeypatch.delenv(name, raising=False)
    clock = Clock()
    timer = cli.Timing(load_settings(tmp_path), clock=clock)
    clock.t = 3.0                     # recorded: 2 s of speech, then the 0.5 s pause and a 0.2 s check
    timer.recorded(quick=True, check_seconds=0.2)
    clock.t = 3.0                     # the transcript came from the check
    timer.mark("transcribe")
    clock.t = 4.1
    timer.mark("route")
    clock.t = 4.2
    timer.mark("act")
    clock.t = 5.4
    timer.mark("speak")
    line = timer.summary("Open Edge.", "open_app")
    assert "listen 3.00 s, transcribe 0.00 s, route 1.10 s, act 0.10 s, speak 1.20 s" in line
    assert "pause waited 0.70 s" in line
    assert "done 1.90 s after you stopped" in line and "reply spoken by 3.10 s" in line


def test_timing_uses_the_pause_the_recording_measured(tmp_path):
    clock = Clock()
    timer = cli.Timing(load_settings(tmp_path), clock=clock)
    clock.t = 3.0
    timer.recorded(quick=True, stats={"quiet": 0.52, "ready": 0.31})
    timer.mark("transcribe")
    line = timer.summary("Open Edge.", "open_app")
    assert "pause waited 0.52 s, text ready 0.31 s after you stopped" in line


# --- filler (plan.md task 7) -------------------------------------------------------

from red.smalltalk import is_filler  # noqa: E402


@pytest.mark.parametrize("said, filler", [
    ("you know", True), ("Hmm.", True), ("okay so", True), ("Um, uh...", True), ("So, well, like", True),
    ("I mean", True), ("", True),
    ("I mean, what is it?", False), ("yeah", False), ("okay", False), ("hey", False), ("what?", False),
    ("open Edge", False), ("you know what, open Edge", False), ("no", False),
])
def test_is_filler(said, filler):
    assert is_filler(said) is filler
