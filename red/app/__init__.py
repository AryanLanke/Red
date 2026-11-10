"""The Red app: a PySide6 window for setup and settings.

    python -m red app

It reads the same RED_HOME\\config\\.env as Red and saves your changes there,
leaving comments and keys it doesn't manage alone.
"""

from __future__ import annotations

import sys
from typing import Callable


def main(settings=None, *, run: Callable | None = None) -> int:
    """Open the app. `run(window)` replaces the Qt event loop (for tests)."""
    try:
        from PySide6.QtWidgets import QApplication

        from .main_window import MainWindow
    except ImportError as e:
        print(f"The Red app needs PySide6 ({e}). Install it with: "
              f"pip install PySide6-Essentials==6.11.3", file=sys.stderr)
        return 1
    if settings is None:
        from red.config import load_settings
        settings = load_settings()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    window = MainWindow(settings)
    if run is not None:
        return run(window)
    window.show()
    return app.exec()
