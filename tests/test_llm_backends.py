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
