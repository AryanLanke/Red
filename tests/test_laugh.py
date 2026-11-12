"""red.laugh: finding laugh words, cutting them out, and loading the bundled clips."""

import numpy as np
import pytest

from red import laugh


def test_has_laugh_finds_the_words_the_model_writes():
    assert laugh.has_laugh("Haha, that's a good one.")
    assert laugh.has_laugh("heh")
    assert laugh.has_laugh("ha ha")
    assert laugh.has_laugh("lol")
    assert not laugh.has_laugh("That's not funny.")
    assert not laugh.has_laugh("haphazard")     # starts like a laugh but isn't one


def test_without_clips_the_text_comes_back_whole():
    assert laugh.split_laughs("Haha, funny.", []) == [("text", "Haha, funny.")]


def test_a_leading_laugh_is_cut_out():
    clip = np.zeros(4, dtype=np.float32)
    assert laugh.split_laughs("Haha, that's good.", [clip], choose=lambda c: c[0]) == [
        ("laugh", clip), ("text", "that's good.")]


def test_a_trailing_laugh_is_cut_out():
    clip = np.zeros(4, dtype=np.float32)
    assert laugh.split_laughs("That's good, haha.", [clip], choose=lambda c: c[0]) == [
        ("text", "That's good"), ("laugh", clip)]


def test_a_run_of_laughs_becomes_one_clip():
    clip = np.zeros(4, dtype=np.float32)
    assert laugh.split_laughs("haha, heh", [clip], choose=lambda c: c[0]) == [("laugh", clip)]


def test_a_mid_sentence_laugh_keeps_the_words_around_it():
    clip = np.zeros(4, dtype=np.float32)
    assert laugh.split_laughs("That's funny, haha, but true.", [clip], choose=lambda c: c[0]) == [
        ("text", "That's funny"), ("laugh", clip), ("text", "but true.")]


def test_load_clips_reads_the_bundled_wavs():
    clips = laugh.load_clips()
    assert len(clips) >= 2
    for clip in clips:
        assert clip.ndim == 1 and clip.dtype == np.float32 and clip.size > 0
        assert float(np.abs(clip).max()) <= 1.0
