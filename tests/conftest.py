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
def _no_real_browser(monkeypatch):
    """No test finds (and so starts) a real browser; the Windows-default opener is a fake."""
    import red.browser
    monkeypatch.setattr(red.browser, "find_exe", lambda exe: None)
