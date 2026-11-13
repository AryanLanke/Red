import sys
from dataclasses import replace

import pytest

from red import llm
from red.config import load_settings
from red.process import ManagedServer, ServerExited, free_port, http_ok


@pytest.fixture
def settings(monkeypatch, tmp_path):
    for name in ("RED_LLM_URL", "RED_LLM_BACKEND", "RED_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return load_settings(tmp_path)


def test_managed_server_starts_and_stops(tmp_path):
    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    server = ManagedServer("http", [sys.executable, "-m", "http.server", str(port),
                                    "--bind", "127.0.0.1", "--directory", str(tmp_path)],
                           url, tmp_path / "http.log")
    server.start(timeout=20)
    assert http_ok(url)
    server.stop()
    assert not http_ok(url)


def test_managed_server_reports_early_exit(tmp_path):
    server = ManagedServer("quitter", [sys.executable, "-c", "raise SystemExit(3)"],
                           "http://127.0.0.1:1/", tmp_path / "q.log")
    with pytest.raises(ServerExited) as info:
        server.start(timeout=20)
    assert info.value.code == 3


def test_external_url_skips_local_backends(monkeypatch, settings):
    monkeypatch.setattr(llm, "start_ollama", lambda s: pytest.fail("should not start"))
    s = replace(settings, llm_url="http://127.0.0.1:9/v1")
    client, server = llm.connect(s)
    assert isinstance(client, llm.OpenAICompatClient) and server is None


def test_auto_falls_back_to_llama_cpp(monkeypatch, settings):
    def broken_ollama(s):
        raise llm.LLMError("no ollama")
    monkeypatch.setattr(llm, "start_ollama", broken_ollama)
    monkeypatch.setattr(llm, "start_llama_server", lambda s: ("http://x/v1", "key", None))
    client, _ = llm.connect(settings)
    assert isinstance(client, llm.OpenAICompatClient)
    assert client.api_key == "key"


def test_ollama_only_does_not_fall_back(monkeypatch, settings):
    def broken_ollama(s):
        raise llm.LLMError("no ollama")
    monkeypatch.setattr(llm, "start_ollama", broken_ollama)
    monkeypatch.setattr(llm, "start_llama_server", lambda s: pytest.fail("should not fall back"))
    s = replace(settings, llm_backend="ollama")
    with pytest.raises(llm.LLMError, match="Ollama backend failed"):
        llm.connect(s)


def test_both_backends_failing_reports_both(monkeypatch, settings):
    monkeypatch.setattr(llm, "start_ollama", lambda s: (_ for _ in ()).throw(llm.LLMError("A")))
    monkeypatch.setattr(llm, "start_llama_server", lambda s: (_ for _ in ()).throw(llm.LLMError("B")))
    with pytest.raises(llm.LLMError) as info:
        llm.connect(settings)
    assert "Ollama: A" in str(info.value) and "llama.cpp: B" in str(info.value)


def test_every_model_has_an_ollama_tag():
    for spec in llm.MODELS.values():
        assert spec.ollama_tag


def test_every_model_is_pinned_by_sha256():
    for name, spec in llm.MODELS.items():
        assert spec.revision and len(spec.revision) == 40, name
        assert spec.files and all(len(a.sha256) == 64 for a in spec.files), name
        assert spec.best_for, name


def capture_post(monkeypatch, reply):
    sent = []

    def post(url, body, headers=None, timeout=120):
        sent.append((url, body))
        return reply
    monkeypatch.setattr(llm, "_post_json", post)
    return sent


def test_qwen35_answers_without_thinking(monkeypatch):
    sent = capture_post(monkeypatch, {"message": {"content": "{}"}})
    spec = llm.MODELS["qwen3.5-4b"]
    llm.OllamaClient("http://x", spec.ollama_tag, thinking=spec.thinking).complete_json("s", "u", {})
    assert sent[0][1]["think"] is False
    llm.OllamaClient("http://x", "qwen2.5:7b-instruct-q4_K_M").complete_json("s", "u", {})
    assert "think" not in sent[1][1]                 # older models don't know the option


def test_ollama_options_pass_through(monkeypatch):
    sent = capture_post(monkeypatch, {"message": {"content": "{}"}})
    llm.OllamaClient("http://x", "m", options={"num_gpu": 0}).complete_json("s", "u", {})
    assert sent[0][1]["options"]["num_gpu"] == 0 and sent[0][1]["options"]["num_ctx"] == 4096


def test_llama_server_gets_enable_thinking_false(monkeypatch):
    sent = capture_post(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    llm.OpenAICompatClient("http://x/v1", "qwen3.5-4b", thinking=True).complete_json("s", "u", {})
    assert sent[0][1]["chat_template_kwargs"] == {"enable_thinking": False}
    llm.OpenAICompatClient("http://x/v1", "other").complete_json("s", "u", {})
    assert "chat_template_kwargs" not in sent[1][1]


class FakeResponse:
    def __init__(self, lines):
        self.lines = [l.encode() for l in lines]

    def __iter__(self):
        return iter(self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_streams_the_reply(monkeypatch):
    sent = []

    def urlopen(req, timeout):
        import json as j
        sent.append(j.loads(req.data))
        return FakeResponse(['{"message": {"content": "{\\"answer\\": \\"Hi"}, "done": false}\n',
                             '\n', 'not json\n',
                             '{"message": {"content": " there\\"}"}, "done": false}\n',
                             '{"message": {"content": ""}, "done": true}\n',
                             '{"message": {"content": "never read"}}\n'])
    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    client = llm.OllamaClient("http://x", "qwen3.5:4b-q4_K_M", thinking=True)
    assert "".join(client.stream_json("s", "u", {"type": "object"})) == '{"answer": "Hi there"}'
    assert sent[0]["stream"] is True and sent[0]["think"] is False and sent[0]["format"] == {"type": "object"}


def test_ollama_stream_error_is_an_llm_error(monkeypatch):
    monkeypatch.setattr(llm.urllib.request, "urlopen",
                        lambda req, timeout: FakeResponse(['{"error": "model not found"}\n']))
    with pytest.raises(llm.LLMError, match="model not found"):
        list(llm.OllamaClient("http://x", "m").stream_json("s", "u", {}))


def test_openai_compatible_server_sent_events(monkeypatch):
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: FakeResponse([
        'data: {"choices": [{"delta": {"content": "{\\"answer\\""}}]}\n', ': keep-alive\n',
        'data: {"choices": [{"delta": {}}]}\n',
        'data: {"choices": [{"delta": {"content": ": \\"ok\\"}"}}]}\n', 'data: [DONE]\n',
        'data: {"choices": [{"delta": {"content": "late"}}]}\n']))
    client = llm.OpenAICompatClient("http://x/v1", "m")
    assert "".join(client.stream_json("s", "u", {})) == '{"answer": "ok"}'


# --- a faster Ollama start (plan.md task 2.1) ---------------------------------

def test_vulkan_is_off_when_an_nvidia_driver_is_present():
    env = llm.ollama_gpu_env(which=lambda name: r"C:\Windows\System32\nvidia-smi.exe", environ={})
    assert env == {"OLLAMA_VULKAN": "0"}


def test_vulkan_stays_on_for_a_pc_with_only_amd_or_intel_graphics():
    assert llm.ollama_gpu_env(which=lambda name: None, environ={}) == {}


def test_the_users_own_ollama_vulkan_wins():
    env = llm.ollama_gpu_env(which=lambda name: "nvidia-smi.exe", environ={"OLLAMA_VULKAN": "1"})
    assert env == {}


def test_ollama_start_waits_long_enough_for_a_cold_boot():
    assert llm.OLLAMA_START_TIMEOUT >= 120


# Real lines from RED_HOME\logs\ollama.log (2026-11-13), shortened.
GPU_LINE = ('time=2026-11-13T05:18:08.740-08:00 level=INFO source=types.go:32 msg="inference compute" id=0 '
            'filter_id=0 library=CUDA compute=8.9 name=CUDA0 description="NVIDIA GeForce RTX 4050 Laptop GPU" '
            'libdirs=ollama,cuda_v13 driver=13.5 pci_id=0000:01:00.0 type=discrete')
CPU_LINE = ('time=2026-11-13T05:18:08.740-08:00 level=INFO source=types.go:32 msg="inference compute" id=cpu '
            'library=cpu compute="" name=cpu description=cpu libdirs=ollama driver="" pci_id="" type=""')


def test_the_gpu_library_is_read_from_ollamas_log():
    assert llm.gpu_library_from_log("other\n" + GPU_LINE + "\n[GIN] ...") == ("CUDA", "cuda_v13")
    assert llm.gpu_library_from_log(CPU_LINE) == ("cpu", "")
    assert llm.gpu_library_from_log("nothing here") is None


def test_the_library_ollama_chose_is_pinned_next_time(tmp_path):
    libs = tmp_path / "lib" / "ollama"
    (libs / "cuda_v13").mkdir(parents=True)
    remembered = tmp_path / "cache" / llm.GPU_LIBRARY_FILE
    assert llm.learn_gpu_library(remembered, GPU_LINE, pinned=False)
    env = llm.ollama_gpu_env(remembered, libs, which=lambda name: "nvidia-smi.exe", environ={})
    assert env == {"OLLAMA_VULKAN": "0", "OLLAMA_LLM_LIBRARY": "cuda_v13"}


def test_a_pin_that_finds_no_gpu_is_dropped_and_ollama_starts_again(tmp_path):
    remembered = tmp_path / llm.GPU_LIBRARY_FILE
    remembered.write_text("cuda_v13")
    assert llm.learn_gpu_library(remembered, CPU_LINE, pinned=True) is False
    assert not remembered.exists()


def test_an_unpinned_start_with_no_gpu_is_fine_and_pins_nothing(tmp_path):
    remembered = tmp_path / llm.GPU_LIBRARY_FILE
    assert llm.learn_gpu_library(remembered, CPU_LINE, pinned=False) is True
    assert not remembered.exists()


def test_a_remembered_library_that_is_gone_or_odd_is_not_pinned(tmp_path):
    libs = tmp_path / "lib" / "ollama"
    libs.mkdir(parents=True)
    remembered = tmp_path / llm.GPU_LIBRARY_FILE
    remembered.write_text("cuda_v13")                    # an Ollama update removed that folder
    assert llm.ollama_gpu_env(remembered, libs, which=lambda n: None, environ={}) == {}
    remembered.write_text("..\\evil")
    assert llm.ollama_gpu_env(remembered, None, which=lambda n: None, environ={}) == {}


def test_the_users_own_ollama_llm_library_wins(tmp_path):
    remembered = tmp_path / llm.GPU_LIBRARY_FILE
    remembered.write_text("cuda_v13")
    env = llm.ollama_gpu_env(remembered, None, which=lambda n: None, environ={"OLLAMA_LLM_LIBRARY": "cpu"})
    assert env == {}
