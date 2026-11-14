import numpy as np
import pytest

import red.audio as audio
from red.stt import (BASE_VOCABULARY, MAX_VOCABULARY_CHARS, WHISPER_MODELS, Transcriber,
                     command_vocabulary, fix_names, read_vocabulary)
from voice_fakes import FakeWhisper, fake_download, tone


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    return calls


def make(tmp_path, device="cpu", cuda=False, fail_load_on=(), fail_transcribe_on=(), fail_after=0, **kw):
    created = []

    def factory(path, dev, compute):
        if dev in fail_load_on:
            raise RuntimeError(f"CUDA failed with error out of memory ({dev})")
        err = RuntimeError("Library cublas64_12.dll is not found") if dev in fail_transcribe_on else None
        m = FakeWhisper(path, dev, compute, fail_on_transcribe=err, fail_after=fail_after)
        created.append(m)
        return m

    t = Transcriber(tmp_path / "whisper", "small", device, model_factory=factory,
                    cuda_check=lambda: cuda, **kw)
    return t, created


def test_loads_on_first_use_only(tmp_path, no_network):
    t, created = make(tmp_path)
    assert not t.loaded and created == [] and no_network == []
    assert t.transcribe(tone(1.0)) == "Open downloads."
    assert t.loaded and len(created) == 1
    t.transcribe(tone(1.0))
    assert len(created) == 1                      # loaded once


def test_downloads_pinned_files_into_models_whisper(tmp_path, no_network):
    t, created = make(tmp_path)
    t.load()
    folder = tmp_path / "whisper" / "small"
    assert created[0].path == str(folder)
    assert {d.name for _, d, _ in no_network} == {"config.json", "model.bin", "tokenizer.json",
                                                   "vocabulary.txt"}
    assert all(u.startswith("https://huggingface.co/Systran/faster-whisper-small/resolve/536b066")
               for u, _, _ in no_network)
    assert all(d.parent == folder for _, d, _ in no_network)


def test_cpu_uses_int8(tmp_path):
    t, created = make(tmp_path, device="cpu", cuda=True)
    t.load()
    assert (t.device, t.compute_type, created[0].compute_type) == ("cpu", "int8", "int8")


def test_auto_uses_gpu_float16_when_cuda_works(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True)
    t.load()
    assert (t.device, created[0].compute_type) == ("cuda", "float16")


def test_auto_uses_cpu_without_cuda(tmp_path):
    t, _ = make(tmp_path, device="auto", cuda=False)
    t.load()
    assert t.device == "cpu"


def test_gpu_load_error_falls_back_to_cpu(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True, fail_load_on=("cuda",))
    assert t.transcribe(tone(1.0)) == "Open downloads."
    assert t.device == "cpu" and [m.device for m in created] == ["cpu"]


def test_explicit_cuda_still_falls_back(tmp_path):
    t, _ = make(tmp_path, device="cuda", fail_load_on=("cuda",))
    t.load()
    assert t.device == "cpu"


def test_gpu_is_warmed_up_at_load(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True)
    t.load()
    assert len(created[0].calls) == 1             # one warm-up run on the GPU
    _, kwargs = created[0].calls[0]
    assert kwargs["vad_filter"] is False          # so the model really runs


def test_missing_cuda_library_is_caught_at_load(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True, fail_transcribe_on=("cuda",))
    t.load()                                      # warm-up fails, so the CPU is used from the start
    assert t.device == "cpu"
    assert [m.device for m in created] == ["cuda", "cpu"]
    assert t.transcribe(tone(1.0)) == "Open downloads."
    assert len(created) == 2


def test_cuda_error_during_transcription_retries_on_cpu(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True, fail_transcribe_on=("cuda",), fail_after=1)
    t.load()
    assert t.device == "cuda"
    assert t.transcribe(tone(1.0)) == "Open downloads."
    assert [m.device for m in created] == ["cuda", "cpu"]
    assert t.device == "cpu"
    t.transcribe(tone(1.0))
    assert len(created) == 2                      # stays on the CPU


def test_cpu_errors_are_not_hidden(tmp_path):
    t, _ = make(tmp_path, device="cpu", fail_transcribe_on=("cpu",))
    with pytest.raises(RuntimeError):
        t.transcribe(tone(1.0))


def test_empty_audio_gives_empty_text_without_loading(tmp_path):
    t, created = make(tmp_path)
    assert t.transcribe(np.zeros(0, np.float32)) == ""
    assert created == []


def test_options_and_text_cleanup(tmp_path):
    def factory(path, dev, compute):
        return FakeWhisper(path, dev, compute, text="  Shut down |  in two   hours. ")

    t = Transcriber(tmp_path, device="cpu", model_factory=factory, cuda_check=lambda: False)
    assert t.transcribe((tone(1.0) * 32767).astype(np.int16)) == "Shut down in two hours."
    audio_in, kwargs = t._model.calls[0]
    assert audio_in.dtype == np.float32
    assert kwargs["language"] == "en" and kwargs["vad_filter"] is True


def test_rejects_unknown_model_and_device(tmp_path):
    with pytest.raises(ValueError):
        Transcriber(tmp_path, model="huge")
    with pytest.raises(ValueError):
        Transcriber(tmp_path, device="tpu")


def test_pins_are_complete():
    for spec in WHISPER_MODELS.values():
        assert "/resolve/" in spec.base_url and "/main/" not in spec.base_url
        assert all(len(a.sha256) == 64 for a in spec.files)


# --- the command vocabulary (plan.md task 2b) -----------------------------------------

def test_hotwords_reach_whisper(tmp_path):
    def factory(path, dev, compute):
        return FakeWhisper(path, dev, compute, text=" Compare Heiko Pilot with Hey Siri. ")

    t = Transcriber(tmp_path, device="cpu", model_factory=factory, cuda_check=lambda: False,
                    hotwords=command_vocabulary())
    assert t.transcribe(tone(1.0)) == "Compare Hey Copilot with Hey Siri."
    assert t._model.calls[0][1]["hotwords"].startswith("Hey Copilot, Hey Siri")


@pytest.mark.parametrize("heard, fixed", [
    ("Can you compare Heiko Pilot with Hey Siri", "Can you compare Hey Copilot with Hey Siri"),
    ("compare Heyco Pilot and Alexa", "compare Hey Copilot and Alexa"),
    ("I heard that heyco-pilot is for Windows", "I heard that Hey Copilot is for Windows"),
    ("the co-pilot landed the plane", "the co-pilot landed the plane"),     # not the assistant
    ("open the pilot episode", "open the pilot episode"),
])
def test_fix_names(heard, fixed):
    assert fix_names(heard) == fixed


def test_vocabulary_is_short_and_has_no_repeats():
    words = command_vocabulary("Spotify", "spotify", "YouTube", "  Task   Manager ", "", "x" * 41,
                               *[f"App {i}" for i in range(100)])
    names = words.split(", ")
    assert names[:len(BASE_VOCABULARY)] == list(BASE_VOCABULARY)
    assert names.count("Spotify") == 1 and "spotify" not in names and names.count("YouTube") == 1
    assert "Task Manager" in names and "x" * 41 not in names
    assert len(words) <= MAX_VOCABULARY_CHARS


# --- the user's vocabulary file (names Whisper mishears) ---------------------------

def test_read_vocabulary_skips_comments_and_blanks(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("# artist names\nLE SSERAFIM\n\n  Arijit Singh  \n# a comment\n"
                    "Crazy # trailing comment\n", encoding="utf-8")
    assert read_vocabulary(path) == ["LE SSERAFIM", "Arijit Singh", "Crazy"]


def test_a_missing_vocabulary_file_is_fine(tmp_path):
    assert read_vocabulary(tmp_path / "nope.txt") == []
    assert read_vocabulary(None) == []


def test_vocabulary_file_names_reach_whisper(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("LE SSERAFIM\nArijit Singh\n", encoding="utf-8")
    t, created = make(tmp_path, vocabulary_file=path)
    t.transcribe(tone(1.0))
    hotwords = created[0].calls[0][1]["hotwords"]
    assert hotwords.startswith("Hey Copilot, Hey Siri")        # the fixed names stay first
    assert "LE SSERAFIM" in hotwords and "Arijit Singh" in hotwords
    assert len(hotwords) <= MAX_VOCABULARY_CHARS + 40          # one comma-joined prompt, still short


def test_vocabulary_edits_apply_without_restarting(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_text("LE SSERAFIM\n", encoding="utf-8")
    t, created = make(tmp_path, vocabulary_file=path)
    t.transcribe(tone(1.0))
    path.write_text("NewJeans\n", encoding="utf-8")
    t.transcribe(tone(1.0))
    second = created[0].calls[1][1]["hotwords"]
    assert "NewJeans" in second and "LE SSERAFIM" not in second


def test_a_broken_vocabulary_file_does_not_stop_transcription(tmp_path):
    path = tmp_path / "vocabulary.txt"
    path.write_bytes(b"\xff\xfe\x00 broken")                    # not UTF-8 at all
    t, created = make(tmp_path, vocabulary_file=path)
    assert t.transcribe(tone(1.0)) == "Open downloads."


# --- the shorter encoder window (night 1) ----------------------------------------

def test_encoder_window_fits_the_clip_in_steps():
    from red.stt import FULL_WINDOW_FRAMES, encoder_frames
    assert encoder_frames(1.0) == 1400          # at least 14 s: shorter windows made Whisper loop
    assert encoder_frames(13.0) == 1400
    assert encoder_frames(13.5) == 1600         # clip + 0.6 s margin, up to the next 2 s step
    assert encoder_frames(15.5) == FULL_WINDOW_FRAMES
    assert encoder_frames(25.0) == FULL_WINDOW_FRAMES


def test_short_window_is_per_thread_and_restored():
    from red import stt
    with stt.short_window(2.0):
        assert stt._window.frames == 1400
        with stt.short_window(20.0):
            assert stt._window.frames is None   # long clips use the model's own 30 s
        assert stt._window.frames == 1400
    assert getattr(stt._window, "frames", None) is None


def test_looping_transcripts_are_spotted():
    from red.stt import looks_looped
    assert looks_looped("open open open open open open")
    assert looks_looped("What's the weather // // // // // //")
    assert not looks_looped("Hey Red red open YouTube")
    assert not looks_looped("")
