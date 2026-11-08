import threading
import time

import numpy as np
import pytest

import red.audio as audio
from red.tts import DEFAULT_VOICE, PIPER_VOICES, Speaker
from voice_fakes import FakePlayer, FakeVoice, fake_download


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    return calls


def make(tmp_path, voice=None, player=None):
    fv = FakeVoice()
    loaded = []

    def loader(path):
        loaded.append(path)
        return fv

    sp = Speaker(tmp_path / "piper", voice, voice_loader=loader, player=player or FakePlayer())
    return sp, fv, loaded


def test_say_blocks_and_plays_all_sentences(tmp_path):
    sp, fv, loaded = make(tmp_path)
    sp.say("Opening Downloads. Done.")
    played = sp.player.played
    assert len(played) == 1
    audio_out, rate = played[0]
    assert rate == 22_050 and audio_out.dtype == np.float32
    assert audio_out.size == (len("Opening Downloads") + len(" Done")) * 10
    assert loaded == [tmp_path / "piper" / f"{DEFAULT_VOICE}.onnx"]
    assert not sp.speaking


def test_default_voice_is_pinned_and_downloaded(tmp_path, no_network):
    sp, _, _ = make(tmp_path)
    sp.say("Hi.")
    urls = [u for u, _, _ in no_network]
    assert len(urls) == 2
    assert all("rhasspy/piper-voices/resolve/e7229f7" in u for u in urls)
    assert {d.name for _, d, _ in no_network} == {f"{DEFAULT_VOICE}.onnx", f"{DEFAULT_VOICE}.onnx.json"}


def test_voice_loads_once(tmp_path):
    sp, _, loaded = make(tmp_path)
    sp.say("One.")
    sp.say("Two.")
    assert len(loaded) == 1


def test_empty_text_says_nothing(tmp_path):
    sp, fv, loaded = make(tmp_path)
    sp.say("   ")
    assert sp.player.played == [] and loaded == []


def test_whitespace_is_collapsed(tmp_path):
    sp, fv, _ = make(tmp_path)
    sp.say("  Shut down\n in two   hours. ")
    assert fv.texts == ["Shut down in two hours."]


def test_non_blocking_say_and_stop(tmp_path):
    player = FakePlayer(auto_finish=False)
    sp, _, _ = make(tmp_path, player=player)
    t0 = time.monotonic()
    sp.say("A long reply.", block=False)
    assert player.started.wait(2)
    assert sp.speaking
    assert time.monotonic() - t0 < 1.0
    sp.stop()
    assert not sp.speaking
    assert player.stops >= 1
    assert not any(t.name == "red-tts" and t.is_alive() for t in threading.enumerate())


def test_new_say_stops_the_previous_one(tmp_path):
    player = FakePlayer(auto_finish=False)
    sp, _, _ = make(tmp_path, player=player)
    sp.say("First.", block=False)
    assert player.started.wait(2)
    stops = player.stops
    player.auto_finish = True
    sp.say("Second.")
    assert player.stops > stops
    assert len(player.played) == 2


def test_stop_from_another_thread_ends_a_blocking_say(tmp_path):
    player = FakePlayer(auto_finish=False)
    sp, _, _ = make(tmp_path, player=player)
    threading.Timer(0.1, sp.stop).start()
    t0 = time.monotonic()
    sp.say("Blocking.")
    assert time.monotonic() - t0 < 2.0


def test_stop_when_idle_is_safe(tmp_path):
    sp, _, _ = make(tmp_path)
    sp.stop()
    sp.stop()


def test_unknown_voice_needs_local_files(tmp_path):
    sp, _, _ = make(tmp_path, voice="en_GB-custom-low")
    with pytest.raises(FileNotFoundError, match="isn't pinned"):
        sp.say("Hi.")
    d = tmp_path / "piper"
    d.mkdir(parents=True, exist_ok=True)
    (d / "en_GB-custom-low.onnx").write_bytes(b"x")
    (d / "en_GB-custom-low.onnx.json").write_text("{}")
    sp.say("Hi.")
    assert len(sp.player.played) == 1


def test_pins_are_complete():
    assert DEFAULT_VOICE in PIPER_VOICES
    for spec in PIPER_VOICES.values():
        assert "/main/" not in spec.base_url
        assert all(len(a.sha256) == 64 for a in spec.files)
