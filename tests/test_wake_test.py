"""python -m red wake-test, with a fake microphone and detector."""

import logging

import numpy as np

from red import wake_test
from red.config import load_settings


class FakeMic:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return np.zeros(1280, np.float32)


def fake_detector(lines):
    class Det:
        def __init__(self):
            self.n = 0

        def score(self, frame):
            self.n += 1
            if self.n <= len(lines):
                logging.getLogger("red.wakeword").info(lines[self.n - 1])
            return 0.0
    return lambda model_dir: Det()


def run(tmp_path, lines, frames):
    ticks = iter(range(frames + 3))
    out = []
    wake_test.run(load_settings(tmp_path), seconds=frames, out=out.append, make_detector=fake_detector(lines),
                  microphone=FakeMic, clock=lambda: float(next(ticks)))
    return "\n".join(out)


def test_it_prints_each_check_with_a_verdict(tmp_path):
    text = run(tmp_path, ["Wake check: heard 'Hey Red' (score 1.00, short phrase, peak 0.40)",
                          "Wake check: heard 'Thank you' (score 0.00, short phrase, peak 0.30)"], 5)
    assert "heard 'Hey Red' (score 1.00, short phrase, peak 0.40)  ->  WAKES RED" in text
    assert "'Thank you' (score 0.00, short phrase, peak 0.30)  ->  ignored" in text
    assert "2 phrases checked, 1 would wake Red" in text


def test_a_quiet_microphone_is_called_out(tmp_path):
    text = run(tmp_path, ["Wake check: heard '' (score 0.00, short phrase, peak 0.01)"], 3)
    assert "quiet" in text and "Input" in text


def test_nothing_checked_explains(tmp_path):
    assert "Nothing was checked" in run(tmp_path, [], 3)
