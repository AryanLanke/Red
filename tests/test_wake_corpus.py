"""wake-test --record and --replay, with a fake microphone and detector."""

import json
import logging

import numpy as np

from red import wake_corpus
from red.audio import SAMPLE_RATE
from red.config import load_settings


class FakeMic:
    """Each read gives 80 ms of a quiet tone."""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return np.full(1280, 0.2, np.float32)


PROMPTS = (("hey-red", "Hey Red", 3, 0.5), ("hey-red-cmd", "Hey Red, open YouTube", 2, 0.5))


def test_record_saves_one_wav_per_take_and_the_talk(tmp_path):
    settings = load_settings(tmp_path)
    out = []
    folder = wake_corpus.record(settings, out=out.append, microphone=FakeMic, prompts=PROMPTS,
                                talk_seconds=1.0)
    names = sorted(p.name for p in folder.glob("*.wav"))
    assert names == ["hey-red-01.wav", "hey-red-02.wav", "hey-red-03.wav",
                     "hey-red-cmd-01.wav", "hey-red-cmd-02.wav", "talk.wav"]
    audio = wake_corpus.read_wav(folder / "hey-red-01.wav")
    assert audio.size == int(0.5 * SAMPLE_RATE)
    assert abs(float(audio.max()) - 0.2) < 0.01
    assert "[3/3] Say \"Hey Red\" now" in "\n".join(out)


def test_record_replaces_an_old_corpus(tmp_path):
    settings = load_settings(tmp_path)
    old = wake_corpus.corpus_dir(settings) / "hey-red-99.wav"
    wake_corpus.write_wav(old, np.zeros(10, np.float32))
    wake_corpus.record(settings, out=lambda s: None, microphone=FakeMic, prompts=PROMPTS[:1],
                       talk_seconds=0)
    assert not old.exists()


class LoudDetector:
    """Wakes where a quiet stretch turns loud, and logs a check like the real one."""

    def __init__(self):
        self.was_quiet = True

    def reset(self):
        pass

    def score(self, frame):
        loud = np.abs(frame).max() > 0.5
        wake = loud and self.was_quiet
        self.was_quiet = not loud
        if wake:
            logging.getLogger("red.wakeword").info("Wake check: heard 'Hey Red' (score 1.00, short phrase, peak 0.90)")
            return 1.0
        return 0.0


def make_corpus(settings, hits, misses, talk_wakes):
    folder = wake_corpus.corpus_dir(settings)
    loud = np.concatenate([np.zeros(4000, np.float32), np.full(2000, 0.9, np.float32)])
    quiet = np.zeros(6000, np.float32)
    for i in range(hits):
        wake_corpus.write_wav(folder / f"hey-red-{i + 1:02d}.wav", loud)
    for i in range(misses):
        wake_corpus.write_wav(folder / f"hey-red-{hits + i + 1:02d}.wav", quiet)
    wake_corpus.write_wav(folder / "hey-red-cmd-01.wav", loud)
    talk = np.concatenate([np.concatenate([quiet, np.full(2000, 0.9, np.float32)])
                           for _ in range(talk_wakes)] + [quiet])
    wake_corpus.write_wav(folder / "talk.wav", talk)


def test_replay_counts_hits_misses_and_false_wakes(tmp_path):
    settings = load_settings(tmp_path)
    make_corpus(settings, hits=3, misses=1, talk_wakes=2)
    out = []
    summary = wake_corpus.replay(settings, out=out.append, make_detector=lambda d: LoudDetector(),
                                 now=lambda: 100.0)
    text = "\n".join(out)
    assert summary["hey-red"] == [3, 4]
    assert summary["hey-red-cmd"] == [1, 1]
    assert summary["false_wakes"] == 2
    assert "\"Hey Red\": 3/4 woke Red (75%)" in text
    assert "missed hey-red-04: never checked" in text
    assert "Normal talk: 2 false wakes" in text
    logged = json.loads((settings.logs_dir / wake_corpus.REPLAY_LOG).read_text().splitlines()[-1])
    assert logged["hey-red"] == [3, 4] and logged["time"] == 100.0


def test_replay_without_a_corpus_says_how_to_record(tmp_path):
    out = []
    assert wake_corpus.replay(load_settings(tmp_path), out=out.append,
                              make_detector=lambda d: LoudDetector()) is None
    assert "--record" in out[0]
