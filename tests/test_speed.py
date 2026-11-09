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
    clock.t = 3.0                     # recorded: 2 s of speech, then the 0.8 s pause and a 0.2 s check
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
    assert "pause waited 1.00 s" in line
    assert "done 2.20 s after you stopped" in line and "reply spoken by 3.40 s" in line


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
