"""Entry point.

    python -m red                          voice: press Ctrl+Alt+R or say "Hey Red", then speak
    python -m red --typed                  type commands instead of speaking
    python -m red --dry-run                type commands, only show the tool calls
    python -m red setup                    download the LLM backend, the model and the voice models
    python -m red doctor                   check that everything Red needs is in place
    python -m red voice-setup              say "Hey Red" a few times so Red learns your voice
    python -m red background               run Red with no window (closing PowerShell won't stop it)
    python -m red stop                     stop the hidden Red; status says whether it runs
    python -m red startup on|off           start Red when you sign in, or stop doing that
    python -m red route "open Downloads"   show the tool call for one command (never runs it)
    python -m red run "open Downloads"     run one typed command

Destructive actions (shutdown, restart) always ask first: aloud in voice
mode, typed in typed mode.
"""

from __future__ import annotations

import argparse
import functools
import logging
import os
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .allowlist import AllowlistError, load_allowlist
from .confirm import Ask, typed_ask, with_fallback
from .config import Settings, load_settings
from .executor import Executor
from .llm import LLMError, connect
from .router import RouteError, Router
from .smalltalk import dismissal_reply, is_goodbye, quick_reply
from .tools import default_registry

log = logging.getLogger("red")

# How long to wait for you to start talking after the beep.
START_TIMEOUT_SECONDS = 8.0
# After an answer Red asks "Anything else?" and keeps listening, up to this
# many follow-ups in a row, so it can never loop forever.
MAX_FOLLOW_UPS = 6
ANYTHING_ELSE = "Anything else you want me to do?"
# Ollama unloads an idle model after keep_alive (5 minutes by default), and
# loading it again takes 10 seconds or more. While Red runs in voice mode it
# asks Ollama to keep the model loaded a little more often than that.
KEEP_WARM_SECONDS = 240.0

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_ALLOWLIST = REPO_ROOT / "allowlist.example.toml"
EXAMPLE_REPOS = REPO_ROOT / "repos.example.toml"
EXAMPLE_CONTACTS = REPO_ROOT / "contacts.example.toml"

MUSIC_TOOLS = {"play_music", "stop_music", "pause_music", "resume_music", "next_song"}
VOICE_HELP = ("Voice needs the voice packages. Install them with "
              "'pip install -r requirements.txt', or use 'python -m red --typed'.")


# --------------------------------------------------------------------------
# Typed mode
# --------------------------------------------------------------------------

def _show(router: Router, command: str) -> None:
    try:
        route = router.route(command)
    except (RouteError, LLMError) as e:
        print(f"  error: {e}")
        return
    print(f"  {route.to_json()}")
    if route.destructive:
        print("  (destructive: will ask for confirmation)")
    logging.getLogger("red.commands").info("%r -> %s", command, route.to_json())


def _run(router: Router, executor: Executor, command: str) -> None:
    quick = dismissal_reply(command) or quick_reply(command)
    if quick is not None:
        logging.getLogger("red.commands").info("%r -> small talk", command)
        print(f"  Red: {quick}")
        return
    try:
        route = router.route(command)
    except (RouteError, LLMError) as e:
        print(f"  Sorry, I didn't get that. ({e})")
        return
    logging.getLogger("red.commands").info("%r -> %s", command, route.to_json())
    if not route.is_none:
        print(f"  -> {route.to_json()}")
    print(f"  Red: {executor.execute(command, route)}")
    if executor.last_details:
        for line in executor.last_details.splitlines():
            print(f"       {line}")


def _typed_loop(handle: Callable[[str], None], banner: str) -> None:
    print(banner)
    while True:
        try:
            command = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if command.lower() in {"quit", "exit"}:
            break
        if command:
            handle(command)


# --------------------------------------------------------------------------
# Voice mode
# --------------------------------------------------------------------------

@dataclass
class Voice:
    """The voice parts, so tests can pass fakes instead of a microphone and models."""

    transcriber: object                        # stt.Transcriber
    speaker: object                            # tts.Speaker
    record: Callable[[], object]               # audio.record_command
    chime: Callable[[], None]                  # audio.chime
    listener_factory: Callable[..., object]    # listener.Listener
    make_ask: Callable[..., Ask]               # voice_confirm.spoken_ask


def load_voice(settings: Settings) -> Voice:
    """The real voice parts. Raises ImportError if the voice packages are missing."""
    from .audio import chime, record_command
    from .listener import Listener
    from .stt import Transcriber
    from .tts import Speaker
    from .voice_confirm import spoken_ask

    models = settings.models_dir
    return Voice(
        transcriber=Transcriber(models / "whisper", settings.whisper_model, settings.whisper_device),
        speaker=Speaker(models / "piper", settings.piper_voice),
        record=functools.partial(record_command,
                                 max_seconds=settings.max_command_seconds,
                                 silence_seconds=settings.end_silence_seconds,
                                 start_timeout=START_TIMEOUT_SECONDS),
        chime=chime,
        listener_factory=Listener,
        make_ask=spoken_ask,
    )


def pretty_hotkey(hotkey: str) -> str:
    """"<ctrl>+<alt>+r" -> "Ctrl+Alt+R"."""
    return "+".join(p.strip("<>").capitalize() if len(p) > 1 else p.upper()
                    for p in hotkey.split("+"))


def pretty_wakeword(wakeword: str) -> str:
    """"hey_red" -> "Hey Red"; a model path -> its file name."""
    return Path(wakeword).stem.replace("_", " ").split(" v0")[0].title()


class VoiceApp:
    """Hotkey or wake word -> listen -> transcribe -> route -> confirm aloud -> run -> answer aloud."""

    def __init__(self, settings: Settings, router: Router, registry, voice: Voice, overlay, *,
                 typed_fallback: Ask = typed_ask, music_player: Callable[[], object] | None = None,
                 log_path: Path | None = None, out: Callable[[str], None] = print,
                 attach: Callable[[Callable[[str], None]], object] | None = None):
        self.settings = settings
        self.router = router
        self.voice = voice
        self.overlay = overlay
        self.out = out
        self._music_player = music_player or _active_music_player
        self._attach = attach  # None: attach_reminders, looked up when run() starts
        spoken = voice.make_ask(voice.speaker, voice.transcriber)

        def ask(question: str, timeout: float) -> str | None:
            self._state("confirm", question)
            self.out(f"  Red asks: {question}")
            return spoken(question, timeout)

        self.executor = Executor(registry, ask=with_fallback(ask, typed_fallback), log_path=log_path)
        self.listener = None
        self.notice = ""        # why the wake word is off, if it is
        self.reminders = None   # red.scheduler's Scheduler, when it exists
        self._turn = threading.RLock()  # one command or reminder at a time

    # --- starting and stopping ------------------------------------------------

    def start_listener(self):
        """Start the hotkey and the wake word. If the wake word can't start, use the hotkey only."""
        s = self.settings
        model_dir = s.models_dir / "wakeword"
        if s.wakeword:
            try:
                listener = self.voice.listener_factory(self.handle, s.hotkey, s.wakeword,
                                                       model_dir=model_dir,
                                                       threshold=s.wakeword_threshold)
                listener.start()
                self.listener = listener
                return listener
            except Exception as e:  # noqa: BLE001 - unknown name, missing model, no microphone
                log.warning("Wake word %r unavailable: %s", s.wakeword, e)
                # The details (which can name other models) go to red.log only.
                self.notice = (f"The wake word \"{pretty_wakeword(s.wakeword)}\" isn't available, "
                               "so only the hotkey works. Details are in red.log.")
        if not s.hotkey:
            raise RuntimeError("The hotkey is off and the wake word isn't available, "
                               "so nothing can start Red. Set RED_HOTKEY in .env.")
        listener = self.voice.listener_factory(self.handle, s.hotkey, None, model_dir=model_dir,
                                               threshold=s.wakeword_threshold)
        listener.start()
        self.listener = listener
        return listener

    def ready_text(self) -> str:
        ways = []
        if self.listener is not None and getattr(self.listener, "hotkey", None):
            ways.append(f"press {pretty_hotkey(self.listener.hotkey)}")
        if self.listener is not None and getattr(self.listener, "wakeword", None):
            ways.append(f"say \"{pretty_wakeword(self.listener.wakeword)}\"")
        text = " or ".join(ways) or "nothing is listening"
        return f"{text[0].upper()}{text[1:]}, then speak."

    def announce(self, text: str) -> None:
        """Say a due reminder. Called by the scheduler from its own thread.

        Waits for a command in progress to finish, and pauses the wake word
        while speaking so Red doesn't hear itself.
        """
        with self._turn:
            player = self._pause_music()
            try:
                self.out(f"Red (reminder): {text}")
                self._state("speaking", text)
                paused = getattr(self.listener, "paused_while", None)
                if paused is not None:
                    with paused():
                        self._speak(text)
                else:
                    self._speak(text)
            finally:
                if player is not None:
                    try:
                        player.resume()
                    except Exception:  # noqa: BLE001
                        log.exception("Couldn't resume the music")
                self._state("idle", text)

    def shutdown(self) -> None:
        if self.reminders is not None and getattr(self.reminders, "on_due", None) == self.announce:
            self.reminders.on_due = None
        for part in (self.listener, self.voice.speaker):
            try:
                if part is not None:
                    part.stop()
            except Exception:  # noqa: BLE001 - best effort while quitting
                log.exception("Error while stopping %r", part)

    def run(self, stop: threading.Event) -> None:
        """Start listening and block until `stop` is set (or Ctrl+C)."""
        self.start_listener()
        self.reminders = (self._attach or attach_reminders)(self.announce)
        if self.notice:
            self.out(self.notice)
        ready = self.ready_text()
        self.out(f"Ready. {ready} Ctrl+C quits.")
        self._state("idle", f"Red is ready. {ready}")
        try:
            while not stop.wait(0.25):
                pass
        finally:
            self.shutdown()

    # --- one command ---------------------------------------------------------

    def handle(self, source: str) -> None:
        """Called by the listener (on its own thread) for each hotkey press or wake word."""
        with self._turn:
            self._handle(source)

    def _handle(self, source: str) -> None:
        """One conversation: a command, then follow-ups until you say you're done."""
        player = self._pause_music()
        tool = None
        last = ""
        try:
            for turn in range(MAX_FOLLOW_UPS + 1):
                if turn:
                    if not last.rstrip().endswith("?"):
                        self._say(ANYTHING_ELSE)     # a reply that asks a question needs no extra one
                    last, tool, again = self._exchange(player, tool, follow_up=True)
                else:
                    last, tool, again = self._exchange(player, tool, follow_up=False)
                if not again or self.settings.follow_up_seconds <= 0:
                    break
        except Exception as e:  # noqa: BLE001 - one bad command must not stop Red
            log.exception("Command failed")
            last = "Sorry, something went wrong."
            self._state("error", f"{last} ({e})")
            self._speak(last)
        finally:
            if player is not None and tool not in MUSIC_TOOLS:
                try:
                    player.resume()
                except Exception:  # noqa: BLE001
                    log.exception("Couldn't resume the music")
            self._state("idle", last)

    def _exchange(self, player, tool, *, follow_up: bool):
        """Listen once and answer. Returns (last reply, tool, whether to keep listening)."""
        self._state("listening", "Listening...")
        self.voice.chime()
        if follow_up:
            audio = self.voice.record(start_timeout=self.settings.follow_up_seconds)
        else:
            audio = self.voice.record()
        if getattr(audio, "size", 0) == 0:
            if follow_up:
                return "", tool, False       # nothing more to do: just go quiet
            last = "I didn't hear anything."
            self._say(last)
            return last, tool, False
        self._state("thinking", "")
        text = (self.voice.transcriber.transcribe(audio) or "").strip()
        if not text:
            last = "Sorry, I didn't catch that."
            self._say(last)
            return last, tool, False
        self.out(f"You said: {text}")
        if follow_up and is_goodbye(text):
            last = "Okay."
            self._say(last)
            return last, tool, False
        bye = dismissal_reply(text)
        if bye is not None:
            logging.getLogger("red.commands").info("%r -> dismissed", text)
            self._say(bye)
            return bye, tool, False
        quick = quick_reply(text)
        if quick is not None:
            logging.getLogger("red.commands").info("%r -> small talk", text)
            self._say(quick)
            return quick, tool, True
        self._state("thinking", f"“{text}”")
        try:
            route = self.router.route(text)
        except (RouteError, LLMError) as e:
            log.warning("Couldn't route %r: %s", text, e)
            last = "Sorry, I didn't understand that."
            self._say(last)
            return last, tool, False
        logging.getLogger("red.commands").info("%r -> %s", text, route.to_json())
        tool = route.tool
        if tool == "check_repos":
            self._state("thinking", "Checking your repos...")
        if tool == "pause_music" and player is not None:
            # Red paused the music only to listen. Let the tool pause it for
            # real, so it says "Paused." and not "already paused".
            player.resume()
        last = self.executor.execute(text, route)
        self._say(last, self.executor.last_details)
        return last, tool, True

    # --- helpers -------------------------------------------------------------

    def _state(self, state: str, text: str = "") -> None:
        try:
            self.overlay.set_state(state, text)
        except Exception:  # noqa: BLE001 - the overlay is only a display
            log.exception("Overlay update failed")

    def _speak(self, text: str) -> None:
        try:
            self.voice.speaker.say(text, block=True)
        except Exception:  # noqa: BLE001 - no speakers: the text is still shown
            log.exception("Couldn't speak")

    def _say(self, reply: str, details: str = "") -> None:
        self.out(f"Red: {reply}")
        for line in details.splitlines():
            self.out(f"     {line}")
        self._state("speaking", f"{reply}\n{details}".strip())
        self._speak(reply)

    def _pause_music(self):
        """Pause music while Red listens and talks. Returns the player if it was paused."""
        try:
            player = self._music_player()
            if player is not None and player.current is not None and not player.paused \
                    and player.pause():
                return player
        except Exception:  # noqa: BLE001
            log.exception("Couldn't pause the music")
        return None


def attach_reminders(on_due: Callable[[str], None]):
    """Send due reminders to `on_due`. Returns the scheduler, or None without red.scheduler."""
    try:
        from .scheduler import default_scheduler
    except ImportError:
        return None
    try:
        scheduler = default_scheduler()
        scheduler.on_due = on_due
    except Exception:  # noqa: BLE001 - reminders are optional; Red still works
        log.exception("Couldn't start reminders")
        return None
    return scheduler


def _print_reminder(text: str) -> None:
    print(f"\n  Red (reminder): {text}\n> ", end="", flush=True)


def _active_music_player():
    try:
        from .tools.music import active_player
    except ImportError:
        return None
    return active_player()


def _keep_alive_is_zero(keep_alive: str) -> bool:
    """RED_LLM_KEEP_ALIVE=0 means "unload right away", so don't keep the model warm."""
    return keep_alive.strip().lower() in {"0", "0s", "0m", "0h"}


def keep_model_warm(llm, stop: threading.Event, every: float = KEEP_WARM_SECONDS,
                    prime: Callable[[], object] | None = None):
    """Load the model now, then keep it loaded until `stop` is set.

    `prime`, if given, runs once after the first load: routing a throwaway
    command makes the model read Red's long tool list now, so the first real
    command doesn't pay for it. Returns the background thread, or None when
    the client can't do this (your own OpenAI-compatible server manages its
    own models). If Red crashes, Ollama still unloads the model after keep_alive.
    """
    warm = getattr(llm, "warm", None)
    if warm is None:
        return None

    def loop() -> None:
        primed = prime is None
        while True:
            try:
                warm()
                if not primed:
                    primed = True
                    prime()
            except Exception as e:  # noqa: BLE001 - a slow first command is the only cost
                log.warning("Couldn't load the model ahead of time: %s", e)
            if stop.wait(every):
                return

    thread = threading.Thread(target=loop, name="red-keep-warm", daemon=True)
    thread.start()
    return thread


def _voice_mode(settings: Settings, router: Router, registry) -> int:
    try:
        voice = load_voice(settings)
    except ImportError as e:
        print(f"error: {VOICE_HELP} ({e})", file=sys.stderr)
        return 2
    from .overlay import run_with_overlay

    print("Loading speech models...", file=sys.stderr)
    try:
        voice.transcriber.load()
        voice.speaker.load()
    except Exception as e:  # noqa: BLE001 - missing files, broken download
        print(f"error: couldn't load the voice models: {e}. Run 'python -m red setup'.",
              file=sys.stderr)
        return 2
    print(f"Whisper is on {voice.transcriber.device} ({voice.transcriber.compute_type}).",
          file=sys.stderr)

    stop = threading.Event()
    apps: list[VoiceApp] = []
    if not _keep_alive_is_zero(settings.llm_keep_alive):
        keep_model_warm(router.llm, stop, prime=lambda: router.route("hello"))

    def worker(overlay) -> None:
        app = VoiceApp(settings, router, registry, voice, overlay,
                       log_path=settings.command_log_path)
        apps.append(app)
        app.run(stop)

    try:
        code = run_with_overlay(worker, style=settings.overlay)
    except KeyboardInterrupt:
        code = 130
    stop.set()
    for app in apps:
        app.shutdown()
    print("\nBye.")
    return 0 if code in (0, 130) else code


# --------------------------------------------------------------------------
# Setup
# --------------------------------------------------------------------------

def _install_examples(settings: Settings) -> None:
    for example, target in ((EXAMPLE_ALLOWLIST, settings.allowlist_path),
                            (EXAMPLE_REPOS, settings.repos_path),
                            (EXAMPLE_CONTACTS, settings.contacts_path)):
        if not target.exists() and example.is_file():
            shutil.copyfile(example, target)
            print(f"Created {target}; edit it to add your own entries.")


def _setup_voice(settings: Settings) -> int:
    """Download and verify the Whisper, Piper and wake word models."""
    try:
        from .listener import download_wakeword
        voice = load_voice(settings)
    except ImportError as e:
        print(f"Skipping the voice models: {VOICE_HELP} ({e})")
        return 1
    print(f"Voice models go in {settings.models_dir}")
    voice.transcriber.download()
    voice.speaker.download()
    if settings.wakeword:
        try:
            download_wakeword(settings.models_dir / "wakeword", settings.wakeword)
        except Exception as e:  # noqa: BLE001 - e.g. a name this version doesn't know yet
            log.warning("Wake word %r unavailable: %s", settings.wakeword, e)
            print(f"The wake word \"{pretty_wakeword(settings.wakeword)}\" isn't available yet, "
                  "so Red will use the hotkey. Details are in red.log.")
    print("Voice models are downloaded and verified.")
    return 0


def _check_allowlist(settings: Settings) -> None:
    try:
        load_allowlist(settings.allowlist_path)
    except AllowlistError as e:
        print(f"warning: {e}", file=sys.stderr)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="red")
    parser.add_argument("--home", metavar="FOLDER",
                        help="use this RED_HOME for this run (the sign-in shortcut uses it)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--typed", action="store_true", help="type commands instead of speaking")
    mode.add_argument("--dry-run", action="store_true",
                      help="type commands and only show the tool call for each, never run it")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("setup", help="download the LLM backend, the model and the voice models")
    sub.add_parser("doctor", help="check that everything Red needs is in place")
    sub.add_parser("voice-setup", help="say \"Hey Red\" a few times so Red learns your voice")
    for name, text in (("background", "run Red with no window"),
                       ("stop", "stop the hidden Red"), ("status", "is the hidden Red running?")):
        sub.add_parser(name, help=text)
    p_startup = sub.add_parser("startup", help="start Red when you sign in: on, off, or show")
    p_startup.add_argument("action", nargs="?", choices=("on", "off"))
    p_route = sub.add_parser("route", help="show the tool call for one command")
    p_route.add_argument("text", nargs="+")
    p_run = sub.add_parser("run", help="run one typed command")
    p_run.add_argument("text", nargs="+")
    args = parser.parse_args(argv)
    if args.home:
        os.environ["RED_HOME"] = args.home   # this process only

    if args.cmd == "doctor":
        from .doctor import main as doctor_main
        return doctor_main()        # only looks: starts nothing, records nothing

    settings = load_settings()
    settings.ensure_dirs()
    if args.cmd == "voice-setup":
        logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s")
        from .voice_setup import main as voice_setup_main
        return voice_setup_main(settings)
    if args.cmd in ("background", "stop", "status"):
        from .background import main as background_main
        return background_main(args.cmd, settings.home)
    if args.cmd == "startup":
        from .startup import main as startup_main
        return startup_main(args.action, settings.home)
    logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "setup":
        _install_examples(settings)
    _check_allowlist(settings)

    print("Starting the local model...", file=sys.stderr)
    try:
        llm, server = connect(settings)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:
        if args.cmd == "setup":
            print(f"Ready: {type(llm).__name__} with model {settings.llm_model}")
            if server:
                server.stop()
                server = None
            return _setup_voice(settings)
        registry = default_registry()
        router = Router(registry, llm)
        if args.cmd == "route":
            _show(router, " ".join(args.text))
            return 0
        executor = Executor(registry, ask=typed_ask, log_path=settings.command_log_path)
        if args.cmd == "run":
            (_show if args.dry_run else lambda r, c: _run(r, executor, c))(router, " ".join(args.text))
            return 0
        if args.dry_run:
            _typed_loop(lambda c: _show(router, c), "Red (dry run). Type a command, or 'quit'.")
            return 0
        if args.typed:
            reminders = attach_reminders(_print_reminder)
            try:
                _typed_loop(lambda c: _run(router, executor, c), "Red. Type a command, or 'quit'.")
            finally:
                if reminders is not None and reminders.on_due is _print_reminder:
                    reminders.on_due = None
            return 0
        return _voice_mode(settings, router, registry)
    finally:
        if server:
            server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
