"""Yes/no confirmation for destructive actions.

Only "y" or "yes" confirms. Anything else, or no answer before the
timeout, cancels. `ask` is pluggable: typed input here, spoken input from
red.voice_confirm.spoken_ask, both with the same signature.
"""

from __future__ import annotations

import string
import sys
import time
from typing import Callable

Ask = Callable[[str, float], "str | None"]  # (question, timeout seconds) -> answer, or None on timeout

DEFAULT_TIMEOUT = 30.0
_YES = {"y", "yes"}
_STRIP = string.whitespace + string.punctuation + "…"


def is_yes(answer: str | None) -> bool:
    """True only for "y" or "yes", ignoring case, surrounding spaces and punctuation ("Yes.")."""
    if answer is None:
        return False
    return answer.strip(_STRIP).lower() in _YES


def _console_readline(timeout: float, msvcrt=None, clock=time.monotonic,
                      sleep=time.sleep) -> str | None:
    """Read one line from the Windows console, or None after `timeout` seconds."""
    if msvcrt is None:
        import msvcrt
    # Drop keys typed before the question appeared, so type-ahead can't answer it.
    while msvcrt.kbhit():
        msvcrt.getwch()
    chars: list[str] = []
    deadline = clock() + timeout
    while clock() < deadline:
        if not msvcrt.kbhit():
            sleep(0.05)
            continue
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            msvcrt.putwch("\r")
            msvcrt.putwch("\n")
            return "".join(chars)
        if ch == "\x03":                 # Ctrl+C: treat as "no"
            msvcrt.putwch("\r")
            msvcrt.putwch("\n")
            return ""
        if ch in ("\x00", "\xe0"):       # arrow and function keys send two codes
            msvcrt.getwch()
            continue
        if ch == "\x08":                 # backspace
            if chars:
                chars.pop()
                for c in "\x08 \x08":
                    msvcrt.putwch(c)
            continue
        chars.append(ch)
        msvcrt.putwch(ch)
    return None


def typed_ask(question: str, timeout: float) -> str | None:
    """Print the question and wait up to `timeout` seconds for a typed answer."""
    print(f"{question} [y/N] ", end="", flush=True)
    if sys.platform == "win32" and sys.stdin is not None and sys.stdin.isatty():
        answer = _console_readline(timeout)
        if answer is None:
            print(f"\n(no answer in {timeout:g} seconds)", flush=True)
        return answer
    # Piped input has no portable timeout. End of input counts as no answer.
    line = sys.stdin.readline() if sys.stdin is not None else ""
    return line.rstrip("\r\n") if line else None


def confirm(question: str, ask: Ask = typed_ask, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """Ask a yes/no question. True only for an explicit yes; errors and timeouts cancel."""
    try:
        answer = ask(question, timeout)
    except Exception:
        return False
    return is_yes(answer)
