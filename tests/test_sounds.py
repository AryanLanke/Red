"""Reaction sound packs (red/sounds.py, scripts/make_sounds.py) and the voice previews."""

import importlib.util
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from red import sounds
from test_avatar import app, window  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent


def write_wav(path: Path, seconds: float = 0.3, rate: int = 24_000, amp: float = 0.2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(seconds * rate)) / rate
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((amp * np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16).tobytes())
    return path


def make_pack(home: Path, pack_id="jp-test", *, licence="Test licence", source="Test source",
              kinds=("giggle", "hover")):
    folder = home / "sounds" / pack_id
    for kind in kinds:
        for n in (1, 2):
            write_wav(folder / f"{kind}_{n}.wav")
    lines = ['name = "Test pack"', 'gender = "female"', 'style = "anime-ja"']
    if licence:
        lines.append(f'license = "{licence}"')
    if source:
        lines.append(f'source = "{source}"')
    (folder / "pack.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def no_voice_watch():
    sounds.watch_voice(None)
    yield
    sounds.watch_voice(None)


def test_packs_lists_the_installed_ones(tmp_path):
    make_pack(tmp_path)
    found = sounds.packs(tmp_path)
    assert list(found) == ["jp-test"]
    pack = found["jp-test"]
    assert pack.gender == "female" and pack.license == "Test licence" and pack.source == "Test source"
    assert sorted(pack.kinds) == ["giggle", "hover"] and len(pack.variants("giggle")) == 2


def test_no_sounds_folder_means_no_packs(tmp_path):
    assert sounds.packs(tmp_path) == {}


@pytest.mark.parametrize("missing", ["licence", "source"])
def test_a_pack_without_a_licence_or_source_is_not_used(tmp_path, missing):
    make_pack(tmp_path, licence="" if missing == "licence" else "L", source="" if missing == "source" else "S")
    assert sounds.packs(tmp_path) == {}
    assert sounds.pick("jp-test", "giggle", tmp_path) is None


def test_a_broken_pack_toml_is_skipped(tmp_path):
    folder = make_pack(tmp_path)
    (folder / "pack.toml").write_text("name = [", encoding="utf-8")
    make_pack(tmp_path, "ok-pack")
    assert list(sounds.packs(tmp_path)) == ["ok-pack"]


def test_pick_gives_a_variant_of_that_kind(tmp_path):
    make_pack(tmp_path)
    seen = {sounds.pick("jp-test", "giggle", tmp_path).name for _ in range(40)}
    assert seen == {"giggle_1.wav", "giggle_2.wav"}
    assert sounds.pick("jp-test", "yawn", tmp_path) is None          # the pack has no yawn
    assert sounds.pick("nope", "giggle", tmp_path) is None
    assert sounds.pick("", "giggle", tmp_path) is None


def test_pick_avoids_the_one_just_played(tmp_path):
    make_pack(tmp_path)
    first = sounds.pick("jp-test", "giggle", tmp_path)
    assert all(sounds.pick("jp-test", "giggle", tmp_path, avoid=first) != first for _ in range(20))


def test_play_starts_the_sound_and_returns(tmp_path):
    clip = write_wav(tmp_path / "a.wav")
    played = []
    assert sounds.play(clip, player=played.append) is True and played == [clip]
    assert sounds.play(None, player=played.append) is False
    assert sounds.play(tmp_path / "missing.wav", player=played.append) is False


def test_play_never_goes_over_reds_voice(tmp_path):
    clip = write_wav(tmp_path / "a.wav")
    speaking = {"on": True}
    sounds.watch_voice(lambda: speaking["on"])
    played = []
    assert sounds.play(clip, player=played.append) is False and played == []
    speaking["on"] = False
    assert sounds.play(clip, player=played.append) is True
    speaking["on"] = True
    assert sounds.play(clip, player=played.append, force=True) is True      # only when asked to


def test_a_failing_player_is_not_an_error(tmp_path):
    def boom(path):
        raise OSError("no sound card")
    assert sounds.play(write_wav(tmp_path / "a.wav"), player=boom) is False


def test_a_broken_voice_check_does_not_mute_the_sounds(tmp_path):
    def boom():
        raise RuntimeError
    sounds.watch_voice(boom)
    assert sounds.play(write_wav(tmp_path / "a.wav"), player=lambda p: None) is True


# --- the builder ---------------------------------------------------------------------------------

def load_make_sounds():
    spec = importlib.util.spec_from_file_location("make_sounds", ROOT / "scripts" / "make_sounds.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_sounds"] = module
    spec.loader.exec_module(module)
    return module


class FakeEngine:
    """Stands in for Kokoro: a tone whose length depends on the phonemes, loud or quiet by voice."""

    def create_phonemes(self, phonemes, voice, speed=1.0):
        seconds = min(0.2 + 0.05 * len(phonemes), 3.0)
        t = np.arange(int(seconds * 24_000)) / 24_000
        amp = 0.5 if voice.startswith("jm") else 0.05
        return (amp * np.sin(2 * np.pi * 200 * t)).astype(np.float32)

    def create(self, text, voice, speed=1.0):                 # English packs: words, not phonemes
        return self.create_phonemes(text, voice, speed)


RECORDED = """
[[source]]
id = "fs1"
page = "https://freesound.org/people/someone/sounds/1/"
url = "https://cdn.freesound.org/previews/0/1-hq.mp3"
sha256 = "00"
author = "someone"
title = "cute giggle.wav"
license = "CC BY 4.0"
license_url = "https://creativecommons.org/licenses/by/4.0/"

[[use]]
source = "fs1"
pack = "jp-female-1"
kind = "giggle"
end = 0.5
"""


def test_the_builder_makes_complete_packs_from_recorded_clips_and_kokoro(tmp_path):
    ms = load_make_sounds()
    sources = tmp_path / "sources.toml"
    sources.write_text(RECORDED, encoding="utf-8")
    recording = write_wav(tmp_path / "fs1.wav", seconds=1.0)
    made = ms.build(ms.PACKS, out=tmp_path / "sounds", engine=FakeEngine(), sources_path=sources,
                    fetcher=lambda src, cache: recording)                 # no network in tests
    assert set(made) == {spec.id for spec in ms.PACKS}
    found = sounds.packs(tmp_path)
    assert set(found) == set(made)
    assert {p.lang for p in found.values()} == {"ja", "en"}
    levels = []
    for pack in found.values():
        assert set(pack.kinds) == set(sounds.KINDS)                      # every kind, recorded or not
        assert "Kokoro" in pack.license
        for kind, files in pack.kinds.items():
            for f in files:
                with wave.open(str(f)) as w:
                    audio = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768
                    assert w.getnframes() / w.getframerate() <= 1.5
                assert abs(audio).max() < 0.95
                if kind == "zip":       # all clicks: it reaches the peak ceiling before the loudness target
                    assert abs(audio).max() > 0.85
                    continue
                levels.append(20 * np.log10(np.sqrt(np.mean(audio ** 2))))
    assert max(levels) - min(levels) < 1.5                               # the same loudness everywhere
    assert {p.gender for p in found.values()} == {"male", "female"}
    girl = found["jp-female-1"]
    assert [f.name for f in girl.variants("giggle")] == ["giggle_1.wav"]   # the recorded clip, not Kokoro
    assert "CC BY 4.0" in girl.license
    assert sounds.credits(tmp_path) == ['"cute giggle.wav" by someone '
                                        '(https://freesound.org/people/someone/sounds/1/), CC BY 4.0']


def test_the_builder_refuses_a_licence_that_may_not_ship(tmp_path):
    ms = load_make_sounds()
    sources = tmp_path / "sources.toml"
    sources.write_text(RECORDED.replace('"CC BY 4.0"', '"CC BY-NC 4.0"'), encoding="utf-8")
    with pytest.raises(ValueError, match="not allowed"):
        ms.load_sources(sources)


def test_the_male_2_pack_is_higher_than_male_1():
    ms = load_make_sounds()
    tone = np.sin(2 * np.pi * 100 * np.arange(24_000) / 24_000).astype(np.float32)
    assert ms.shift_pitch(tone, 5).size < tone.size and ms.shift_pitch(tone, 0) is tone


def test_every_kind_has_two_japanese_and_two_english_fallbacks():
    ms = load_make_sounds()
    assert ms.KINDS == sounds.KINDS
    assert set(ms.JA) | {"zip"} == set(sounds.KINDS) == set(ms.EN) | {"zip"}     # the zip is made, not said
    assert all(len(words) == 2 and all(words) for words in ms.EN.values())
    from red.tts_kokoro import VOCAB
    for variants in ms.JA.values():
        assert len(variants) == 2
        for label, phonemes in variants:
            assert label and phonemes
            assert all(c in VOCAB for c in phonemes), phonemes           # Kokoro knows every symbol


# --- voice previews ------------------------------------------------------------------------------

class PreviewEngine:
    def __init__(self):
        self.calls = []

    def create(self, text, voice, speed=1.0):
        self.calls.append((text, voice))
        return np.ones(2400, np.float32) * 0.1


def test_preview_voice_makes_a_wav_once(tmp_path):
    engine = PreviewEngine()
    path = sounds.preview_voice("af_bella", "Hi there, this is Remy.", tmp_path, engine=engine)
    assert path.is_file() and path.suffix == ".wav" and path.parent == tmp_path / "cache" / "voice-preview"
    with wave.open(str(path)) as w:
        assert w.getframerate() == 24_000 and w.getnchannels() == 1 and w.getnframes() > 2400
    assert sounds.preview_voice("af_bella", "Hi there, this is Remy.", tmp_path, engine=engine) == path
    assert len(engine.calls) == 1                                          # the second came from the cache
    other = sounds.preview_voice("am_michael", "Hi there, this is Remy.", tmp_path, engine=engine)
    assert other != path


def test_preview_voice_checks_its_input(tmp_path):
    with pytest.raises(ValueError):
        sounds.preview_voice("xx_nobody", "hello", tmp_path, engine=PreviewEngine())
    with pytest.raises(ValueError):
        sounds.preview_voice("af_bella", "   ", tmp_path, engine=PreviewEngine())


def test_preview_voice_without_kokoro_says_so(tmp_path):
    with pytest.raises(FileNotFoundError):
        sounds.preview_voice("af_bella", "hello", tmp_path)


# --- the companion plays them ----------------------------------------------------------------------

def test_picking_up_and_hovering_play_the_companions_pack(window, tmp_path, monkeypatch):
    w = window.window
    make_pack(tmp_path, "jp-male-1", kinds=("pickup", "drop", "hover", "surprised", "happy"))
    w.state_file = tmp_path / "cache" / "companion.json"
    played = []
    monkeypatch.setattr(sounds, "play", played.append)
    w._sound(w.pickup_clips, "pickup")
    assert len(played) == 1 and played[0].name.startswith("pickup_") and window.played == []
    w._sound(w.drop_clips, "drop")
    assert len(played) == 1 and window.played == []         # held back: one reaction a second at most
    window.clock.t += 1.1
    w._sound(w.drop_clips, "drop")
    assert played[-1].name.startswith("drop_")
    window.clock.t += 1.1
    assert w._react("hover", every=12.0) is True and played[-1].name.startswith("hover_")
    count = len(played)
    window.clock.t += 1.1
    w._react("hover", every=12.0)
    assert len(played) == count                                            # not again within 12 s
    w.quiet = True
    window.clock.t += 20
    assert w.react("poke") is True and len(played) == count                # quiet mode: no sounds
    assert w.react("not a kind") is False


def test_no_pack_falls_back_to_the_old_clips(window, tmp_path):
    w = window.window
    w.state_file = tmp_path / "cache" / "companion.json"                   # no sounds folder there
    w._sound(w.pickup_clips, "pickup")
    assert len(window.played) == 1 and "pickup" in window.played[0].name


def test_reactions_stay_quiet_while_red_talks(window, tmp_path, monkeypatch):
    w = window.window
    make_pack(tmp_path, "jp-male-1", kinds=("pickup",))
    w.state_file = tmp_path / "cache" / "companion.json"
    played = []
    monkeypatch.setattr(sounds, "play", played.append)
    sounds.watch_voice(lambda: True)
    w._sound(w.pickup_clips, "pickup")
    assert played == [] and window.played == []
