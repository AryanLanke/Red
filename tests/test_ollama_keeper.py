"""A stuck Ollama of Red's own is started again (red.llm.OllamaKeeper)."""

import socket
import threading
import urllib.error

import pytest

from red import llm


class FakeServer:
    def __init__(self, name="old"):
        self.name, self.stopped = name, 0

    def stop(self):
        self.stopped += 1


def client(url="http://127.0.0.1:5000"):
    return llm.OllamaClient(url, "qwen3.5:4b", keep_alive="5m")


# --- what counts as a stall ---------------------------------------------------

def _chained(outer, inner):
    try:
        try:
            raise inner
        except BaseException as e:
            raise outer from e
    except BaseException as e:
        return e


@pytest.mark.parametrize("error, stall", [
    (TimeoutError("timed out"), True),
    (socket.timeout("timed out"), True),
    (urllib.error.URLError(TimeoutError("timed out")), True),
    (_chained(llm.LLMError("The LLM server stopped answering (timed out)"), TimeoutError()), True),
    (urllib.error.URLError(ConnectionRefusedError()), False),     # nothing there: not a hang
    (llm.LLMError("LLM server error 500: boom"), False),
    (ValueError("bad json"), False),
    (None, False),
])
def test_is_stall(error, stall):
    assert llm.is_stall(error) is stall


# --- the client reports stalls ------------------------------------------------

def test_a_timed_out_reply_reports_a_stall(monkeypatch):
    def hang(url, body, **kw):
        raise TimeoutError("timed out")
    monkeypatch.setattr(llm, "_post_json", hang)
    c, seen = client(), []
    c.on_stall = seen.append
    with pytest.raises(TimeoutError):
        c.complete_json("s", "u", {})
    assert seen == ["timed out"]


def test_a_server_error_is_not_a_stall(monkeypatch):
    def fail(url, body, **kw):
        raise llm.LLMError("LLM server error 500: model not found")
    monkeypatch.setattr(llm, "_post_json", fail)
    c, seen = client(), []
    c.on_stall = seen.append
    with pytest.raises(llm.LLMError):
        c.complete_json("s", "u", {})
    assert seen == []


def test_a_stream_that_stops_mid_reply_reports_a_stall(monkeypatch):
    def lines(url, body, **kw):
        yield {"message": {"content": '{"reply": "Hey'}}
        raise llm.LLMError("The LLM server stopped answering (timed out)") from TimeoutError()
    monkeypatch.setattr(llm, "_stream_lines", lines)
    c, seen = client(), []
    c.on_stall = seen.append
    pieces = []
    with pytest.raises(llm.LLMError):
        for piece in c.stream_json("s", "u", {}):
            pieces.append(piece)
    assert pieces == ['{"reply": "Hey'] and len(seen) == 1


def test_closing_a_stream_early_is_not_a_stall(monkeypatch):
    monkeypatch.setattr(llm, "_stream_lines", lambda url, body, **kw: iter(
        [{"message": {"content": "a"}}, {"message": {"content": "b"}}]))
    c, seen = client(), []
    c.on_stall = seen.append
    stream = c.stream_json("s", "u", {})
    assert next(stream) == "a"
    stream.close()
    assert seen == []


def test_warm_gives_up_in_90_s_and_reports_the_stall(monkeypatch):
    waited = []

    def hang(url, body, timeout=120):
        waited.append(timeout)
        raise TimeoutError("timed out")
    monkeypatch.setattr(llm, "_post_json", hang)
    c, seen = client(), []
    c.on_stall = seen.append
    with pytest.raises(TimeoutError):
        c.warm()
    assert waited == [llm.WARM_TIMEOUT_SECONDS] == [90.0] and seen == ["timed out"]


def test_a_broken_stall_handler_never_hides_the_real_error(monkeypatch):
    monkeypatch.setattr(llm, "_post_json", lambda url, body, **kw: (_ for _ in ()).throw(TimeoutError()))
    c = client()
    c.on_stall = lambda reason: 1 / 0
    with pytest.raises(TimeoutError):
        c.complete_json("s", "u", {})


# --- the keeper ---------------------------------------------------------------

class Starts:
    def __init__(self, url="http://127.0.0.1:6000/", gate=None):
        self.url, self.gate, self.calls, self.servers = url, gate, 0, []

    def __call__(self, settings):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(2)
        server = FakeServer(f"new{self.calls}")
        self.servers.append(server)
        return self.url, server


def keeper(start, clock=None, **kw):
    c, old = client(), FakeServer()
    warmed = []
    c.warm = lambda: warmed.append(c.base_url)
    k = llm.OllamaKeeper(object(), c, old, start=start, clock=clock or (lambda: 0.0), **kw)
    return k, c, old, warmed


def test_a_stall_stops_the_old_ollama_starts_a_new_one_and_loads_the_model():
    start = Starts()
    k, c, old, warmed = keeper(start)
    assert c.on_stall == k.stalled                       # the client is wired to the keeper
    k.stalled("timed out").join(2)
    assert old.stopped == 1 and start.calls == 1
    assert k.server is start.servers[0] and k.restarts == 1
    assert c.base_url == "http://127.0.0.1:6000"         # trailing slash dropped
    assert warmed == ["http://127.0.0.1:6000"]           # warmed at the new address


def test_restarts_are_spaced_out():
    now = [1000.0]
    start = Starts()
    k, *_ = keeper(start, clock=lambda: now[0], min_gap=180)
    k.stalled("timed out").join(2)
    now[0] += 60
    assert k.stalled("timed out") is None                # too soon
    now[0] += 130
    k.stalled("timed out").join(2)
    assert start.calls == 2


def test_only_one_restart_at_a_time():
    gate = threading.Event()
    start = Starts(gate=gate)
    k, *_ = keeper(start, min_gap=0)
    first = k.stalled("timed out")
    assert k.stalled("timed out again") is None          # a reply and the warm-up both timed out
    gate.set()
    first.join(2)
    assert start.calls == 1


def test_a_failed_restart_can_be_tried_again_later():
    now = [0.0]
    calls = []

    def start(settings):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("ollama did not become ready")
        return "http://127.0.0.1:7000", FakeServer("new")
    k, c, old, _ = keeper(start, clock=lambda: now[0], min_gap=180)
    k.stalled("timed out").join(2)
    assert k.server is None and c.base_url == "http://127.0.0.1:5000"
    now[0] += 200
    k.stalled("timed out").join(2)
    assert c.base_url == "http://127.0.0.1:7000" and k.server.name == "new"


def test_stop_ends_the_current_server_and_no_restart_after():
    start = Starts()
    k, c, old, _ = keeper(start, min_gap=0)
    k.stop()
    assert old.stopped == 1 and k.server is None
    assert k.stalled("timed out") is None and start.calls == 0


def test_quitting_during_a_restart_stops_the_new_server_too():
    gate = threading.Event()
    start = Starts(gate=gate)
    k, *_ = keeper(start)
    thread = k.stalled("timed out")
    k.stop()
    gate.set()
    thread.join(2)
    assert start.servers[0].stopped == 1 and k.server is None


def test_only_reds_own_ollama_gets_a_keeper():
    c, server = client(), FakeServer()
    assert llm.keep_ollama_alive(object(), c, None) is None            # the user's own Ollama
    other = object()
    assert llm.keep_ollama_alive(object(), other, server) is server    # llama-server
    k = llm.keep_ollama_alive(object(), c, server)
    assert isinstance(k, llm.OllamaKeeper) and k.server is server
