import numpy as np
import pytest

import red.audio as audio
from red.stt import WHISPER_MODELS, Transcriber
from voice_fakes import FakeWhisper, fake_download, tone


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    calls = []
    monkeypatch.setattr(audio, "download", fake_download(calls))
    return calls


def make(tmp_path, device="cpu", cuda=False, fail_load_on=(), fail_transcribe_on=(), **kw):
    created = []

    def factory(path, dev, compute):
        if dev in fail_load_on:
            raise RuntimeError(f"CUDA failed with error out of memory ({dev})")
        err = RuntimeError("Library cublas64_12.dll is not found") if dev in fail_transcribe_on else None
        m = FakeWhisper(path, dev, compute, fail_on_transcribe=err)
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


def test_cuda_error_during_transcription_retries_on_cpu(tmp_path):
    t, created = make(tmp_path, device="auto", cuda=True, fail_transcribe_on=("cuda",))
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
