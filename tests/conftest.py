import sys
from pathlib import Path

import pytest

# Make the red package importable when running pytest from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _NoWindows:
    """Tests never look at or activate real windows (see red.windows)."""

    def __init__(self, target):
        self.target = target

    def add_pid(self, pid):
        pass

    def __call__(self):
        return False


@pytest.fixture(autouse=True)
def _no_window_fronting(monkeypatch):
    import red.windows
    monkeypatch.setattr(red.windows, "watch", _NoWindows)


@pytest.fixture(autouse=True)
def _no_real_searxng(monkeypatch):
    """No test starts Red's SearXNG, even with RED_HOME pointing at a real install."""
    import red.searxng

    def refuse(settings, **kwargs):
        raise RuntimeError("tests never start SearXNG")

    def no_install(settings, **kwargs):
        pass                    # setup tests: no download, no venv, no pip

    monkeypatch.setattr(red.searxng, "start", refuse)
    monkeypatch.setattr(red.searxng, "install", no_install)


@pytest.fixture(autouse=True)
def _always_connected(monkeypatch):
    """Look-ups behave the same whether or not the test machine is online."""
    import red.tools.online
    monkeypatch.setattr(red.tools.online, "connected", lambda: True)


@pytest.fixture(autouse=True)
def _no_real_memory(monkeypatch, tmp_path):
    """No test reads or writes the user's own memory (RED_HOME\\memory), and no learner thread runs."""
    import red.memory
    monkeypatch.setattr(red.memory, "memory_dir", lambda home: tmp_path / "memory")
    monkeypatch.setattr(red.memory.Learner, "start", lambda self: None)
    import red.greeter
    monkeypatch.setattr(red.greeter.Greeter, "start", lambda self: None)   # no real idle checks or hellos


@pytest.fixture(autouse=True)
def _no_real_browser(monkeypatch):
    """No test finds (and so starts) a real browser; the Windows-default opener is a fake."""
    import red.browser
    monkeypatch.setattr(red.browser, "find_exe", lambda exe: None)
