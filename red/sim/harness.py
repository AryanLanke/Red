"""The simulated world around Red's real turn loop.

`SimWorld.say("open Edge")` runs one turn through `VoiceApp._exchange`, the same method a spoken
command goes through: clean-up of fillers, small talk, switching companions, the gate, the router,
the tools, Chat (with the companion's persona and the memory), the speech stream. Only the edges
are fake: the "microphone" returns a prepared sentence, the "speaker" records what it was asked
to say, and every tool runs in dry run (the call is recorded, nothing happens on the PC).

Everything lives in a temporary RED_HOME, so the user's memory, companion choice and logs are never
touched. The model is the real one (the hidden Red's Ollama): pass its client in.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from .. import __main__ as cli
from .. import companions, events
from ..config import load_settings
from ..router import Router
from ..tools import default_registry

log = logging.getLogger(__name__)

# Tools that really run, because they only touch the temporary memory.
LIVE_TOOLS = {"remember", "what_you_know", "forget"}

# What a dry-run tool says. The text is plausible, so the next turn has something to talk about.
CANNED = {
    "play_online": "Playing {query} on YouTube.",
    "open_app": "Opening {app}.",
    "open_url": "Opening {url}.",
    "open_folder": "Opening {folder}.",
    "look_up": "Here's what I found about {topic}: it is well known, with a long history. (simulated)",
    "answer": "Here's a short answer to that. (simulated)",
    "weather": "It's 21 degrees and clear. (simulated)",
    "news": "Three headlines today. (simulated)",
    "describe_screen": "You're in a code editor with a file open. (simulated)",
    "set_reminder": "Okay, I'll remind you.",
    "set_timer": "Timer set.",
    "stop_music": "Stopped.",
    "shutdown": "Shutting down.",
}


class Audio:
    """Looks like a recorded clip: `size` is all the voice loop looks at."""

    def __init__(self, size: int = 16_000):
        self.size = size


class FakeTranscriber:
    """Hands out the next prepared sentence, as if Whisper had heard it."""
    device, compute_type = "cpu", "int8"

    def __init__(self):
        self.queue: list[str] = []

    def transcribe(self, audio) -> str:
        return self.queue.pop(0) if self.queue else ""

    def load(self) -> None:
        pass


class FakeSpeaker:
    """Records each piece Red says, with the time it was handed over (= the first word)."""

    speaking = False

    def __init__(self):
        self.said: list[str] = []
        self.times: list[float] = []

    def say(self, text: str, block: bool = True) -> None:
        self.said.append(text)
        self.times.append(time.perf_counter())

    def stop(self) -> None:
        pass

    def load(self) -> None:
        pass


class FakeOverlay:
    def __init__(self):
        self.states: list[tuple[str, str]] = []

    def set_state(self, state: str, text: str = "") -> None:
        self.states.append((state, text))


class Tap:
    """Wraps the real client: counts and times every model call, and says which ones were the router's."""

    def __init__(self, inner, router_prompt=lambda: ""):
        self._inner = inner
        self._router_prompt = router_prompt
        self.calls: list[dict] = []
        if hasattr(inner, "stream_json"):          # Chat streams only if the client can
            self.stream_json = self._stream_json

    def __getattr__(self, name):          # options, base_url, model ...
        return getattr(self._inner, name)

    def _note(self, kind: str, system: str, seconds: float, first: float | None = None) -> None:
        self.calls.append({"kind": kind, "router": system == self._router_prompt(),
                           "seconds": seconds, "first": first, "at": time.perf_counter()})

    def complete_json(self, system, user, schema, *args, **kwargs):
        start = time.perf_counter()
        try:
            return self._inner.complete_json(system, user, schema, *args, **kwargs)
        finally:
            self._note("complete", system, time.perf_counter() - start)

    def _stream_json(self, system, user, schema, *args, **kwargs):
        start = time.perf_counter()
        first = None
        try:
            for piece in self._inner.stream_json(system, user, schema, *args, **kwargs):
                if first is None:
                    first = time.perf_counter() - start
                yield piece
        finally:
            self._note("stream", system, time.perf_counter() - start, first)


@dataclass
class Turn:
    """What happened for one line of the user."""
    meant: str                      # what the user meant to say
    heard: str                      # what Whisper made of it (the same, unless the scenario misheard it)
    companion: str                  # who was on duty when it was said
    reply: str = ""                 # what Red answered (the last reply of the turn)
    spoken: list[str] = field(default_factory=list)
    tool: str = "none"              # the tool that ran ("none": talk), several joined with "+"
    args: dict = field(default_factory=dict)
    calls: list[dict] = field(default_factory=list)       # every tool call this turn: {tool, args}
    via: str = ""                   # quick | switch | dismissed | name | filler | gate | fast | router | stop
    status: str = ""
    asked: list[str] = field(default_factory=list)        # confirmation questions Red asked
    confirmed: bool | None = None
    first_word: float = 0.0         # seconds from the transcript to Red's first word
    total: float = 0.0              # seconds until the reply was complete
    router_calls: int = 0
    chat_calls: int = 0
    companion_after: str = ""
    again: bool = False             # Red keeps listening (asked something back, or a debate)
    error: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


def _canned(tool: str, args: dict) -> str:
    text = CANNED.get(tool)
    if text is None:
        return "Done."
    try:
        return text.format(**{k: v for k, v in args.items()}) if args else text
    except (KeyError, IndexError):
        return text.split("{")[0].rstrip() or "Done."


class SimWorld:
    """One user sitting at one PC with Red. Make one per conversation (it has its own memory)."""

    def __init__(self, llm, *, real_home: Path | None = None, companion: str = "red",
                 memory_facts: list[str] | None = None, confirm: str = "no",
                 keep_home: bool = False, router_llm=None):
        import os
        for var in ("RED_COMPANION",):
            os.environ.pop(var, None)
        self.real_home = Path(real_home or os.environ.get("RED_HOME") or r"D:\RED")
        self.home = Path(tempfile.mkdtemp(prefix="red-sim-"))
        self._keep_home = keep_home
        self._seed_home()
        self.settings = load_settings(self.home)
        self.tap = Tap(llm)
        self.confirm_answer = confirm            # what the user says when Red asks "Shut down?"
        self.calls: list[dict] = []
        self.asked: list[str] = []
        self.speaker = FakeSpeaker()
        self.transcriber = FakeTranscriber()
        self.overlay = FakeOverlay()
        self.log_path = self.home / "logs" / "commands.jsonl"
        self._log_pos = 0
        self.capture = _Capture()
        self.registry = self._dry_registry()
        self.router = Router(self.registry, self.tap)
        self.tap._router_prompt = lambda: self.router.system_prompt
        self._patch_background()
        voice = cli.Voice(transcriber=self.transcriber, speaker=self.speaker,
                          record=self._record, chime=lambda: None,
                          listener_factory=None, make_ask=self._make_ask)
        self.app = cli.VoiceApp(self.settings, self.router, self.registry, voice, self.overlay,
                                typed_fallback=lambda q, t: "no", log_path=self.log_path,
                                out=lambda line: None)
        self.app._prime_chat = lambda: None               # no head-start call; the turn pays for itself
        self.chat = self.app.chat
        self.chat.learner = None
        self._tool = None                                 # the last tool of the conversation (the gate looks at it)
        self._again = False
        self.companion = companion
        self.set_companion(companion)
        for fact in memory_facts or ():
            self.chat.memory.add(fact)
        self.turns: list[Turn] = []
        self._next_audio = Audio(16_000)

    # --- set up -----------------------------------------------------------------

    def _seed_home(self) -> None:
        """Copy what Red reads (allowlist, contacts, personality, the user's companion edits). Never
        the memory, logs, models or the .env."""
        for rel in ("config/allowlist.toml", "config/contacts.toml", "config/personality.txt"):
            src = self.real_home / rel
            if src.is_file():
                dst = self.home / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        edits = self.real_home / "companions"
        if edits.is_dir():
            shutil.copytree(edits, self.home / "companions", dirs_exist_ok=True)

    def _dry_registry(self):
        registry = default_registry(google=False, plugins=True, home=self.real_home)
        world = self
        for tool in registry:
            if tool.name in LIVE_TOOLS:
                continue
            original_run = tool.run

            def run(*, _tool=tool, **kwargs):
                world.calls.append({"tool": _tool.name, "args": dict(kwargs)})
                return _canned(_tool.name, kwargs)

            tool.run = run
            tool._real_run = original_run
        return registry

    def _patch_background(self) -> None:
        """No learner thread, no greeter: the same switches tests/conftest.py throws."""
        from .. import memory
        memory.Learner.start = lambda self: None                     # type: ignore[method-assign]

    def _record(self, **kwargs):
        return self._next_audio

    def _make_ask(self, speaker, transcriber):
        def ask(question: str, timeout: float = 0) -> str:
            self.asked.append(question)
            return self.confirm_answer
        return ask

    def set_companion(self, companion_id: str) -> None:
        companions.set_active(companion_id, self.home)
        self.companion = companion_id

    def active(self) -> str:
        return companions.active_id(self.home)

    # --- one turn ----------------------------------------------------------------

    def say(self, meant: str, heard: str | None = None, follow_up: bool | None = None) -> Turn:
        """The user says `meant`; Whisper hears `heard` (default: the same). Returns what happened."""
        heard = meant if heard is None else heard
        turn = Turn(meant=meant, heard=heard, companion=self.active())
        self.transcriber.queue = [heard]
        self.calls.clear()
        self.asked.clear()
        self.speaker.said.clear()
        self.speaker.times.clear()
        self.tap.calls.clear()
        self.capture.lines.clear()
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(self.capture)
        root.setLevel(logging.INFO)
        before = self._log_size()
        marks: dict = {}

        def note_heard(text=""):
            marks.setdefault("heard_at", time.perf_counter())
        off = events.on("heard", note_heard)
        t0 = time.perf_counter()
        try:
            last, tool, again = self.app._exchange(self._tool, follow_up=bool(follow_up if follow_up is not None
                                                                              else self._again))
        except Exception as e:  # noqa: BLE001 - a crash is a result too
            log.exception("The turn crashed")
            last, tool, again = "", self._tool, False
            turn.error = f"{type(e).__name__}: {e}"
        finally:
            off()
            root.removeHandler(self.capture)
            root.setLevel(old_level)
        end = time.perf_counter()
        start = marks.get("heard_at", t0)
        turn.reply = last
        turn.again = bool(again)
        turn.spoken = list(self.speaker.said)
        turn.first_word = (self.speaker.times[0] - start) if self.speaker.times else (end - start)
        turn.total = end - start
        turn.calls = list(self.calls)
        turn.asked = list(self.asked)
        turn.companion_after = self.active()
        turn.router_calls = sum(1 for c in self.tap.calls if c["router"])
        turn.chat_calls = sum(1 for c in self.tap.calls if not c["router"])
        entries = self._log_entries(before)
        self._fill_from_log(turn, entries, tool)
        turn.via = self._via(turn)
        self._tool = tool
        self._again = bool(again)
        self.turns.append(turn)
        return turn

    def _log_size(self) -> int:
        try:
            return self.log_path.stat().st_size
        except OSError:
            return 0

    def _log_entries(self, before: int) -> list[dict]:
        try:
            with self.log_path.open("rb") as f:
                f.seek(before)
                data = f.read().decode("utf-8", "replace")
        except OSError:
            return []
        out = []
        for line in data.splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return out

    def _fill_from_log(self, turn: Turn, entries: list[dict], tool) -> None:
        real = [e for e in entries if e.get("tool") not in (None, "none")]
        if real:
            turn.tool = "+".join(e["tool"] for e in real)
            turn.args = real[0].get("args", {})
            turn.status = real[-1].get("status", "")
            turn.confirmed = real[-1].get("confirmed")
        elif entries:
            turn.tool, turn.status = "none", entries[-1].get("status", "none")
        elif turn.calls:
            turn.tool = turn.calls[0]["tool"]
        if not turn.args and turn.calls:
            turn.args = turn.calls[0]["args"]

    def _via(self, turn: Turn) -> str:
        text = " | ".join(self.capture.lines).lower()
        for key, name in (("small talk", "quick"), ("switch companion", "switch"), ("dismissed", "dismissed"),
                          ("-> name", "name"), ("filler", "filler"), ("stop the idle song", "stop"),
                          ("fast path", "fast")):
            if key in text:
                return name
        if turn.router_calls:
            return "router"
        if turn.tool == "none" and turn.chat_calls:
            return "gate"
        return "other"

    # --- done ----------------------------------------------------------------------

    def close(self) -> None:
        if not self._keep_home:
            shutil.rmtree(self.home, ignore_errors=True)

    def __enter__(self) -> "SimWorld":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
