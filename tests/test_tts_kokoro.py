"""Kokoro voice: no model, no sound device (fakes), except the espeak phoneme check."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from red.config import load_settings
from red.tts import Speaker
from red.tts_kokoro import (DEFAULT_VOICE, KOKORO_FILES, MODEL_FILE, PAUSE_SECONDS, SAMPLE_RATE,
                            VOCAB, VOICES, VOICES_FILE, KokoroEngine, KokoroSpeaker, make_speaker,
                            speakable, trim)
from tests.voice_fakes import FakePlayer, FakeVoice


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RED_TTS", "RED_VOICE", "RED_VOICE_SPEED", "RED_PIPER_VOICE", "RED_HOME"):
        monkeypatch.delenv(name, raising=False)


class FakeEngine:
    def __init__(self, fail=False):
        if fail:
            raise RuntimeError("model broken")
        self.calls = []

    def create(self, text, voice, speed=1.0):
        self.calls.append((text, voice, speed))
        return np.full(len(text) * 10, 0.2, np.float32)


def kokoro_files(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / MODEL_FILE).write_bytes(b"model")
    (folder / VOICES_FILE).write_bytes(b"voices")
    return folder


def piper(tmp_path, player=None):
    sp = Speaker(tmp_path / "piper", voice_loader=lambda p: FakeVoice(), player=player or FakePlayer())
    sp.download = lambda: sp.model_path          # never the real 63 MB voice
    return sp


def make(tmp_path, *, files=True, loader=None, fallback=True, voice=None, player=None):
    folder = kokoro_files(tmp_path / "kokoro") if files else tmp_path / "kokoro"
    engines = []

    def default_loader(model, voices):
        engines.append(FakeEngine())
        return engines[-1]

    sp = KokoroSpeaker(folder, voice, fallback=piper(tmp_path) if fallback else None,
                       engine_loader=loader or default_loader, player=player or FakePlayer())
    return sp, engines


# --- the files ---------------------------------------------------------------------------

def test_files_are_pinned_to_a_release_and_a_checksum():
    assert {a.filename for a in KOKORO_FILES.files} == {MODEL_FILE, VOICES_FILE}
    assert all(len(a.sha256) == 64 for a in KOKORO_FILES.files)
    assert "/releases/download/model-files-v1.0/" in KOKORO_FILES.base_url
    assert DEFAULT_VOICE in VOICES and len(VOCAB) == 114


# --- speaking -------------------------------------------------------------------------------

def test_synthesize_uses_the_voice_speed_and_spoken_forms_with_a_breath(tmp_path):
    sp, engines = make(tmp_path, voice="am_michael")
    sp.speed = 1.1
    audio, rate = sp.synthesize("Meet at 10:00 a.m.")
    assert rate == SAMPLE_RATE and not sp.using_fallback
    assert engines[0].calls == [("Meet at 10 AM", "am_michael", 1.1)]
    tail = int(PAUSE_SECONDS * SAMPLE_RATE)
    assert audio.size == len("Meet at 10 AM") * 10 + tail and not audio[-tail:].any()


def test_say_speaks_sentence_by_sentence(tmp_path):
    player = FakePlayer()
    sp, engines = make(tmp_path, player=player)
    sp.say("First one. Second one! Third?", block=True)
    assert [c[0] for c in engines[0].calls] == ["First one.", "Second one!", "Third?"]
    assert len(player.played) == 3 and all(rate == SAMPLE_RATE for _, rate in player.played)


def test_unknown_voice_falls_back_to_the_default(tmp_path):
    sp, _ = make(tmp_path, voice="zz_nobody")
    assert sp.voice_name == DEFAULT_VOICE


# --- Piper behind it ----------------------------------------------------------------------

def test_missing_files_speak_with_piper(tmp_path):
    player = FakePlayer()
    sp, engines = make(tmp_path, files=False, player=player)
    audio, rate = sp.synthesize("Hello there.")
    assert sp.using_fallback and engines == [] and rate == 22_050 and audio.size
    assert sp.fallback.player is player                  # stop() stops either voice


def test_a_broken_model_speaks_with_piper(tmp_path):
    def broken(model, voices):
        raise RuntimeError("onnxruntime says no")
    sp, _ = make(tmp_path, loader=broken)
    sp.load()
    assert sp.using_fallback
    assert sp.synthesize("Hi.")[1] == 22_050


def test_without_a_fallback_a_missing_model_is_an_error(tmp_path):
    sp, _ = make(tmp_path, files=False, fallback=False)
    with pytest.raises(FileNotFoundError):
        sp.load()


def test_download_fetches_kokoro_and_piper(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(type(KOKORO_FILES), "ensure", lambda self, d, label=None: got.append(("kokoro", d)) or d)
    sp, _ = make(tmp_path, files=False)
    sp.fallback.download = lambda: got.append(("piper",))
    assert sp.download() == sp.model_path
    assert got == [("kokoro", tmp_path / "kokoro"), ("piper",)]


def test_make_speaker_follows_the_settings(monkeypatch, tmp_path):
    k = make_speaker(load_settings(tmp_path))
    assert isinstance(k, KokoroSpeaker) and isinstance(k.fallback, Speaker)
    assert k.voice_dir == tmp_path / "models" / "kokoro"
    monkeypatch.setenv("RED_TTS", "piper")
    p = make_speaker(load_settings(tmp_path))
    assert type(p) is Speaker


# --- settings ------------------------------------------------------------------------------

def test_voice_settings(monkeypatch, tmp_path):
    s = load_settings(tmp_path)
    assert (s.tts, s.voice, s.voice_speed) == ("kokoro", "af_heart", 1.0)
    monkeypatch.setenv("RED_VOICE", "bm_george")
    monkeypatch.setenv("RED_VOICE_SPEED", "1.15")
    s = load_settings(tmp_path)
    assert (s.voice, s.voice_speed) == ("bm_george", 1.15)


@pytest.mark.parametrize("name, value", [("RED_TTS", "elevenlabs"), ("RED_VOICE_SPEED", "3"),
                                         ("RED_VOICE_SPEED", "fast")])
def test_bad_voice_settings_are_errors(monkeypatch, tmp_path, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        load_settings(tmp_path)


# --- the engine ----------------------------------------------------------------------------

class FakeSession:
    def __init__(self, path):
        self.feeds = []

    def get_inputs(self):
        return [SimpleNamespace(name=n) for n in ("tokens", "style", "speed")]

    def run(self, outputs, feed):
        self.feeds.append(feed)
        audio = np.concatenate([np.zeros(2000), np.full(4000, 0.5), np.zeros(2000)]).astype(np.float32)
        return [audio[None, :]]


def test_engine_feeds_tokens_style_and_speed_and_trims(tmp_path, monkeypatch):
    import red.tts_kokoro as k
    styles = np.arange(510 * 256, dtype=np.float32).reshape(510, 1, 256)
    np.savez(tmp_path / "voices.npz", af_heart=styles)
    monkeypatch.setattr(k, "phonemize", lambda text, language: "hˈeɪ")
    engine = KokoroEngine(tmp_path / "model.onnx", tmp_path / "voices.npz", session_factory=FakeSession)
    audio = engine.create("Hey", "af_heart", 1.2)
    feed = engine.session.feeds[0]
    assert feed["tokens"].tolist() == [[0, VOCAB["h"], VOCAB["ˈ"], VOCAB["e"], VOCAB["ɪ"], 0]]
    assert np.array_equal(feed["style"], styles[3])         # 4 phonemes: row 3
    assert feed["speed"].tolist() == pytest.approx([1.2])
    # 2000 silent samples at each end; trimmed down to a short margin (40 ms = 960 samples + a frame).
    assert 4000 <= audio.size <= 4000 + 2 * (960 + 512)


def test_trim_keeps_quiet_audio_whole():
    silent = np.zeros(3000, np.float32)
    assert trim(silent).size == 3000


def test_phonemes_match_kokoro_onnx():
    pytest.importorskip("piper")
    from red.tts_kokoro import phonemize
    # The same phonemes kokoro-onnx made for this line (checked 2026-11-09).
    assert phonemize("Hey, I'm doing pretty good, honestly.") == "hˈeɪ, aɪm dˌuːɪŋ pɹˈɪɾi ɡˈʊd, ˈɑːnɪstli."
    assert "ʲ" not in phonemize("the CEO of Microsoft")


# --- written forms, the way they are said --------------------------------------------------

@pytest.mark.parametrize("written, said", [
    ("Shut down in 2 hours, at 11:40 PM?", "Shut down in 2 hours, at 11 40 PM?"),
    ("Meet at 10:00 a.m. & bring e.g. snacks.", "Meet at 10 AM and bring for example, snacks."),
    ("It is 23°C and 80% humid (light rain).", "It is 23 degrees Celsius and 80 percent humid, light rain."),
    ("Windows 11 came out in 2021, after XP in 2001.", "Windows 11 came out in 20 21, after XP in 2001."),
    ("Born 1905, died 1999.", "Born 19 oh 5, died 19 99."),
    ("About 8,849 metres; 2048 MB free.", "About 8,849 metres; 2048 MB free."),
    ("It ran for 1500 hours.", "It ran for 1500 hours."),
    ("Back at 9:05.", "Back at 9 oh 5."),
])
def test_speakable(written, said):
    assert speakable(written) == said


# --- the companion's voice (night 1) ---------------------------------------------------------

@pytest.fixture
def no_voice_env(monkeypatch):
    for name in ("RED_VOICE", "RED_VOICE_SPEED", "RED_COMPANION", "RED_TTS"):
        monkeypatch.delenv(name, raising=False)
    yield
    from red import events
    events.clear()


def test_red_speaks_with_a_mans_voice_by_default(no_voice_env, tmp_path):
    from red.tts_kokoro import companion_voice
    voice, speed = companion_voice(load_settings(tmp_path))
    assert voice == "am_michael" and speed == 1.0
    assert make_speaker(load_settings(tmp_path)).voice_name == "am_michael"


def test_remy_and_asha_speak_with_women_voices(no_voice_env, monkeypatch, tmp_path):
    from red.tts_kokoro import companion_voice
    monkeypatch.setenv("RED_COMPANION", "remy")
    assert companion_voice(load_settings(tmp_path)) == ("af_bella", 1.05)
    monkeypatch.setenv("RED_COMPANION", "asha")
    assert companion_voice(load_settings(tmp_path))[0].startswith("af_")


def test_a_voice_the_user_pinned_wins(no_voice_env, monkeypatch, tmp_path):
    from red.tts_kokoro import companion_voice
    monkeypatch.setenv("RED_VOICE", "bm_george")
    monkeypatch.setenv("RED_VOICE_SPEED", "0.9")
    assert companion_voice(load_settings(tmp_path)) == ("bm_george", 0.9)


def test_the_users_own_companion_file_changes_the_voice(no_voice_env, tmp_path):
    from red.tts_kokoro import companion_voice
    folder = tmp_path / "companions" / "red"
    folder.mkdir(parents=True)
    (folder / "companion.toml").write_text('voice = { id = "bm_george", speed = 0.95 }\n', encoding="utf-8")
    assert companion_voice(load_settings(tmp_path)) == ("bm_george", 0.95)


def test_switching_companion_switches_the_voice(no_voice_env, monkeypatch, tmp_path):
    from red import companions, events
    speaker = make_speaker(load_settings(tmp_path))
    assert speaker.voice_name == "am_michael"
    monkeypatch.setenv("RED_COMPANION", "remy")          # set_active keeps this in step
    events.emit("companion", id="remy")
    assert speaker.voice_name == "af_bella" and speaker.speed == 1.05
    events.emit("companion", id="red")
    assert speaker.voice_name == "am_michael" and speaker.speed == 1.0


def test_an_unknown_voice_is_not_taken(no_voice_env, tmp_path):
    speaker = make_speaker(load_settings(tmp_path), follow_companion=False)
    speaker.set_voice("xx_nobody")
    assert speaker.voice_name == "am_michael"


def test_british_voices_use_an_espeak_voice_that_exists():
    from red.tts_kokoro import _language
    assert _language("bm_george") == "en-gb-x-rp" and _language("am_michael") == "en-us"


def test_british_phonemes_really_work_with_pipers_espeak():
    pytest.importorskip("piper")
    from red.tts_kokoro import _language, phonemize
    assert phonemize("Hello there.", _language("bm_george"))      # raised "Failed to set voice: en-gb" before
