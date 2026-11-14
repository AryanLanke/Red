"""Entry point.

    python -m red                          voice: press Ctrl+Alt+R or say "Hey Red", then speak
    python -m red --typed                  type commands instead of speaking
    python -m red --dry-run                type commands, only show the tool calls
    python -m red setup                    download the LLM backend, the model and the voice models
    python -m red doctor                   check that everything Red needs is in place
    python -m red app                      open the setup and settings window
    python -m red voice-setup              say "Hey Red" a few times so Red learns your voice
    python -m red wake-test                see what the wake word hears from your microphone
    python -m red wake-test --record       record your own "Hey Red" takes (about 5 minutes)
    python -m red wake-test --replay       score the wake word on those recordings, offline
    python -m red wake-test --learn        learn how Whisper hears your "Hey Red" from them
    python -m red background               run Red with no window (closing PowerShell won't stop it)
    python -m red hotkey                   watch Ctrl+Alt+R and start Red when it isn't running
    python -m red stop                     stop the hidden Red; status says whether it runs
    python -m red startup on|off           start Red when you sign in, or stop doing that
    python -m red google-login             optional: let Red use your Gmail, Calendar and Contacts
    python -m red google-logout            sign Red out of Google again
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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import companions, events
from .allowlist import AllowlistError, load_allowlist
from .confirm import Ask, typed_ask, with_fallback
from .config import Settings, load_settings
from .executor import Executor, run_later
from .llm import LLMError, connect
from .router import RouteError, Router
from .chat import Chat, make_chat
from .smalltalk import dismissal_reply, is_filler, is_goodbye, quick_reply, sounds_finished
from .speech import SpeechStream, speaking_to
from .tools import default_registry

log = logging.getLogger("red")
STARTED = time.perf_counter()      # for the "Startup:" lines in red.log (plan.md task 2.3)


def since_start() -> float:
    return time.perf_counter() - STARTED

# How long to wait for you to start talking after the beep.
START_TIMEOUT_SECONDS = 8.0
# After chat, a reply that asks you something, or a failure, Red keeps
# listening (without "Anything else?": the chime says it's listening), up to
# this many follow-ups in a row, so it can never loop forever. After an
# action it just goes quiet.
MAX_FOLLOW_UPS = 6
# In a debate the user needs longer to think of their reply than for "anything else?".
DEBATE_FOLLOW_UP_SECONDS = 15.0
# How long the spoken reply may wait for a tool's follow-through work.
LATER_WAIT_SECONDS = 6.0
# Ollama unloads an idle model after keep_alive (5 minutes by default), and
# loading it again takes 10 seconds or more. While Red runs in voice mode it
# asks Ollama to keep the model loaded a little more often than that.
KEEP_WARM_SECONDS = 240.0

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_ALLOWLIST = REPO_ROOT / "allowlist.example.toml"
EXAMPLE_REPOS = REPO_ROOT / "repos.example.toml"
EXAMPLE_CONTACTS = REPO_ROOT / "contacts.example.toml"

# Lines of the conversation the router sees, to understand "that series".
CONTEXT_LINES = 4

# Tools that tell you something. After their answer Red asks if you want
# more and keeps listening; after an action it goes quiet.
INFO_TOOLS = frozenset({"answer", "look_up", "weather", "news", "describe_screen"})
# The user's own wording first. Taken in turn, so the same one never comes twice in a row.
FOLLOW_UP_QUESTIONS = (
    "Anything more you want to know about it?",
    "Want to know more?",
    "Anything else you want to know about it?",
    "Should I go into more detail?",
)
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


def _run(router: Router, executor: Executor, command: str, chat: Chat | None = None) -> None:
    if is_filler(command):
        print("  (nothing to do)")
        return
    named = chat.take_name(command) if chat is not None else None   # "call me Ari" (red/memory.py)
    if named is not None:
        print(f"  Red: {named}")
        return
    switched = companions.handle_switch(command)           # "switch to Remy"
    if switched is not None:
        print(f"  {switched}")
        if chat is not None:
            chat.remember(command, switched)
        return
    quick = dismissal_reply(command) or quick_reply(command, name=chat.user_name() if chat else None)
    if quick is not None:
        logging.getLogger("red.commands").info("%r -> small talk", command)
        print(f"  Red: {quick}")
        if chat is not None:
            chat.remember(command, quick)
        return
    try:
        steps = router.route_many(command, context=chat.history(CONTEXT_LINES) if chat else "")
    except (RouteError, LLMError) as e:
        print(f"  Sorry, I didn't get that. ({e})")
        return
    if len(steps) > 1:
        replies = []
        for part, step in steps:
            logging.getLogger("red.commands").info("%r -> %s", part, step.to_json())
            print(f"  -> {step.to_json()}")
            replies.append((part, executor.execute(part, step), executor.last_status))
            executor.finish()
            if replies[-1][2] in ("error", "cancelled"):
                break
        print(f"  Red: {steps_reply(replies, len(steps))}")
        return
    route = steps[0][1]
    logging.getLogger("red.commands").info("%r -> %s", command, route.to_json())
    if not route.is_none:
        print(f"  -> {route.to_json()}")
    talk = (lambda said, fallback: chat.reply(said, fallback=fallback)) if chat else None
    reply = executor.execute(command, route, talk=talk)
    executor.finish()
    if chat is not None and not route.is_none:
        chat.remember(command, reply)
    print(f"  Red: {reply}")
    if executor.last_details:
        for line in executor.last_details.splitlines():
            print(f"       {line}")


def steps_reply(done: list[tuple[str, str, str]], total: int) -> str:
    """One reply for several commands: each step's reply, or where it stopped and why.

    done is [(the words, the reply, the status)] for the steps that ran, in order.
    """
    said = [reply.strip() for _, reply, status in done if status not in ("error", "cancelled")]
    if done and done[-1][2] in ("error", "cancelled"):
        part, reply, status = done[-1]
        step = len(done)
        if status == "cancelled":
            said.append(f"I stopped at step {step}, {part}, so I didn't do the rest."
                        if step < total else f"I didn't do step {step}, {part}.")
        else:
            rest = " I stopped there." if step < total else ""
            said.append(f"Step {step}, {part}, didn't work: {reply.strip()}{rest}")
    return " ".join(s if s.endswith((".", "!", "?")) else s + "." for s in said)


def bind_conversation(registry, chat: Chat) -> None:
    """Give tools that answer questions the conversation, so "it" and "that" make sense."""
    for tool in registry:
        bind = getattr(tool, "bind_context", None)
        if callable(bind):
            bind(chat.history)
        bind = getattr(tool, "bind_memory", None)        # remember, what_you_know, forget
        if callable(bind) and getattr(chat, "memory", None) is not None:
            bind(chat.memory)


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

# One or two words ("Hope.") might be the start of more: wait this long instead of the quick pause.
SHORT_REPLY_SILENCE = 0.8


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
    from .voice_confirm import spoken_ask

    models = settings.models_dir
    return Voice(
        # Greedy decoding (beam 1) heard as well as beam 5 and is faster; 8 threads on a PC with the cores
        # (scripts/voice_bench.py, progress.md "Hearing fast").
        transcriber=Transcriber(models / "whisper", settings.whisper_model, settings.whisper_device,
                                beam_size=1, cpu_threads=8 if (os.cpu_count() or 0) >= 12 else 0,
                                hotwords=vocabulary(settings),
                                vocabulary_file=settings.vocabulary_path),
        speaker=make_speaker(settings),
        record=functools.partial(record_command,
                                 max_seconds=settings.max_command_seconds,
                                 silence_seconds=settings.end_silence_seconds,
                                 quick_silence=settings.quick_end_silence_seconds,
                                 speculate_after=settings.speculate_after_seconds,
                                 start_timeout=START_TIMEOUT_SECONDS),
        chime=chime,
        listener_factory=Listener,
        make_ask=spoken_ask,
    )


def make_speaker(settings: Settings):
    """Kokoro (natural) with Piper behind it, or Piper alone (RED_TTS=piper)."""
    from .tts_kokoro import make_speaker as make
    return make(settings)


def vocabulary(settings: Settings) -> str:
    """Whisper's hotwords: assistant and browser names, your allowlisted apps and your contacts."""
    from .stt import command_vocabulary

    names: list[str] = []
    try:
        from .allowlist import load_allowlist
        names += [n.title() for n in load_allowlist(settings.allowlist_path).app_names()]
    except Exception:  # noqa: BLE001 - a broken allowlist.toml must not stop the voice
        log.warning("Couldn't read the allowlist for Whisper's vocabulary", exc_info=True)
    try:
        from .tools.mail import load_contacts
        names += [n.title() for n in load_contacts(settings.contacts_path)]
    except Exception:  # noqa: BLE001
        log.warning("Couldn't read the contacts for Whisper's vocabulary", exc_info=True)
    return command_vocabulary(*names)


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
                 typed_fallback: Ask = typed_ask,
                 log_path: Path | None = None, out: Callable[[str], None] = print,
                 attach: Callable[[Callable[[str], None]], object] | None = None):
        self.settings = settings
        self.router = router
        self.voice = voice
        self.overlay = overlay
        self.out = out
        self._attach = attach  # None: attach_reminders, looked up when run() starts
        spoken = voice.make_ask(voice.speaker, voice.transcriber)

        def ask(question: str, timeout: float) -> str | None:
            self._state("confirm", question)
            self.out(f"  Red asks: {question}")
            return spoken(question, timeout)

        self.executor = Executor(registry, ask=with_fallback(ask, typed_fallback), log_path=log_path)
        self.chat = make_chat(router.llm, settings)      # conversation with memory, for anything that isn't a command
        bind_conversation(registry, self.chat)
        for tool in registry:
            bind = getattr(tool, "bind_announce", None)
            if callable(bind):
                bind(self.announce)         # notify_when_done speaks when the app finishes
        self.listener = None
        self.notice = ""        # why the wake word is off, if it is
        self.reminders = None   # red.scheduler's Scheduler, when it exists
        self._turn = threading.RLock()  # one command or reminder at a time
        self._next_question = 0         # which FOLLOW_UP_QUESTIONS comes next
        self._stream: SpeechStream | None = None   # what Red is saying right now, if streamed
        self._interrupted = False       # "Hey Red" (or the hotkey) while Red was talking
        self._interruptible = False

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
                self._wire_interrupt(listener)
                log.info("Startup: listening for \"Hey Red\", %.1f s after Red started", since_start())
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
        self._wire_interrupt(listener)
        return listener

    def _wire_interrupt(self, listener) -> None:
        if hasattr(listener, "on_interrupt"):
            listener.on_interrupt = self.interrupt

    def interrupt(self) -> None:
        """Hey Red (or the hotkey) while Red is talking: stop talking and listen."""
        if not self._interruptible:
            return
        log.info("Interrupted while speaking")
        self._interrupted = True
        stream = self._stream
        if stream is not None:
            stream.cancel()
        try:
            self.voice.speaker.stop()
        except Exception:  # noqa: BLE001
            log.exception("Couldn't stop speaking")

    def _allow_interrupt(self, on: bool) -> None:
        """While Red talks, the wake word listens again, so you can cut in."""
        if on == self._interruptible:
            return
        self._interruptible = on
        allow = getattr(self.listener, "allow_interrupt", None)
        if allow is not None:
            try:
                allow(on)
            except Exception:  # noqa: BLE001 - only a nicety; Red still answers
                log.exception("Couldn't change the wake word while speaking")

    def ready_text(self) -> str:
        ways = []
        if self.listener is not None and getattr(self.listener, "hotkey", None):
            ways.append(f"press {pretty_hotkey(self.listener.hotkey)}")
        if self.listener is not None and getattr(self.listener, "wakeword", None):
            ways.append(f"say \"{pretty_wakeword(self.listener.wakeword)}\"")
        text = " or ".join(ways) or "nothing is listening"
        return f"{text[0].upper()}{text[1:]}, then speak."

    def announce(self, text: str, label: str = "reminder") -> None:
        """Say a due reminder. Called by the scheduler from its own thread.

        Waits for a command in progress to finish, and pauses the wake word
        while speaking so Red doesn't hear itself.
        """
        with self._turn:
            try:
                self.out(f"Red ({label}): {text}")
                self._state("speaking", text)
                paused = getattr(self.listener, "paused_while", None)
                if paused is not None:
                    with paused():
                        self._speak(text)
                else:
                    self._speak(text)
            finally:
                self._state("idle", text)

    def greet(self, text: str) -> bool:
        """A hello from red/greeter.py: said only when Red is free, never queued behind a command."""
        if not self._turn.acquire(blocking=False):
            return False
        try:
            self.announce(text, label="hello")
        finally:
            self._turn.release()
        return True

    def shutdown(self) -> None:
        greeter = getattr(self, "greeter", None)
        if greeter is not None:
            greeter.stop()
        idle = getattr(self, "idle", None)
        if idle is not None:
            idle.stop()
        hotkey = getattr(getattr(self, "chat_window", None), "hotkey", None)
        if hotkey is not None:
            try:
                hotkey.stop()
            except Exception:  # noqa: BLE001 - best effort while quitting
                log.exception("Couldn't stop the chat window hotkey")
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
        from .greeter import attach_greeter
        self.greeter = attach_greeter(self)     # hello, never a briefing (RED_CHATTINESS)
        from . import actions
        actions.bind(self)                      # the companion menu's back end (red/actions.py)
        from .idle import attach_idle
        self.idle = attach_idle(self)           # looks around, grumbles, plays a song (red/idle.py)
        from . import chat_window
        self.chat_window = chat_window.attach_chat_window(self)   # Ctrl+Alt+Space or "open chat"
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
        tool = None
        last = ""
        take = getattr(self.listener, "take_wake_audio", None)
        prefix = take() if source == "wakeword" and take is not None else None
        try:
            for turn in range(MAX_FOLLOW_UPS + 1):
                last, tool, again = self._exchange(tool, follow_up=bool(turn),
                                                   prefix=None if turn else prefix)
                # A debate keeps listening even with follow-ups off: that's the whole point.
                if not again or not (self.settings.follow_up_seconds > 0 or self.chat.is_debate):
                    break
        except Exception as e:  # noqa: BLE001 - one bad command must not stop Red
            log.exception("Command failed")
            last = "Sorry, something went wrong."
            self._state("error", f"{last} ({e})")
            self._speak(last)
        finally:
            self._state("idle", last)

    def _record(self, follow_up: bool, prefix=None):
        """Record one command. `prefix`: speech heard with the wake word, to carry on from.

        Returns (audio, its transcript if a pause check already made one, what the recording
        measured: how long the pause was, and when the text was ready).
        """
        heard: dict = {}
        stats: dict = {}

        def is_complete(audio):
            # A short pause: if what you said so far is a whole sentence,
            # stop now and keep this transcript instead of making another.
            start = time.perf_counter()
            text = (self.voice.transcriber.transcribe(audio) or "").strip()
            heard.update(size=getattr(audio, "size", None), text=text,
                         seconds=time.perf_counter() - start)
            if not sounds_finished(text):
                return False
            # "Hope." or "Yes." may be the start of more: a little longer for one or two words.
            return True if len(text.split()) >= 3 else max(SHORT_REPLY_SILENCE, 0.0)

        kwargs: dict = {"stats": stats}
        if follow_up:
            timeout = self.settings.follow_up_seconds
            if self.chat.is_debate:
                timeout = max(timeout, DEBATE_FOLLOW_UP_SECONDS)
            kwargs["start_timeout"] = timeout
        if self.settings.quick_end_silence_seconds > 0:
            kwargs["is_complete"] = is_complete
        if prefix is not None:
            kwargs["prefix"] = prefix
        audio = self.voice.record(**kwargs)
        if heard and heard["size"] == getattr(audio, "size", None):
            return audio, heard["text"], stats
        return audio, None, stats

    def _exchange(self, tool, *, follow_up: bool, prefix=None):
        """Listen once and answer. Returns (last reply, tool, whether to keep listening).

        `prefix`: "Hey Red, open..." said in one breath. You're already talking, so no chime:
        the recording carries on from it, and "Hey Red" is taken off the transcript.
        """
        self._state("listening", "Listening...")
        if not follow_up:
            self._prime_chat()
        if prefix is None:
            self.voice.chime()
        timer = Timing(self.settings)
        audio, early, stats = self._record(follow_up, prefix)
        timer.recorded(quick=early is not None, stats=stats)
        if getattr(audio, "size", 0) == 0:
            if follow_up:
                if self.chat.is_debate:
                    self.chat.end_debate()   # they stopped answering: the debate is over
                return "", tool, False       # nothing more to do: just go quiet
            last = "I didn't hear anything. Could you say it again?"
            self._say(last)
            return last, tool, True
        self._state("thinking", "")
        text = early if early is not None else (self.voice.transcriber.transcribe(audio) or "").strip()
        timer.mark("transcribe")
        if prefix is not None:
            from .wakeword import strip_wake_phrase
            text = strip_wake_phrase(text, getattr(self.listener, "wake_personal", frozenset()))
            if not text:
                # Only "Hey Red" after all: ask for the command the usual way.
                return self._exchange(tool, follow_up=follow_up)
        if not text:
            last = "Sorry, I didn't catch that. Could you say it again?"
            self._say(last)
            return last, tool, True
        self.out(f"You said: {text}")
        events.emit("heard", text=text)            # the bubble shows the user's words (plan.md 0.1 item 11)
        if is_filler(text):
            # "you know", "hmm": nothing to do. Said first, you're probably
            # still thinking, so listen once more; in a follow-up, go quiet.
            logging.getLogger("red.commands").info("%r -> filler, ignored", text)
            return "", tool, not follow_up
        if self.chat.debate_ends(text):
            # "stop", "you win", "I give up": Chat closes the debate in its own words.
            last = self.chat.reply(text)
            self._say(last)
            return last, tool, False
        if follow_up and is_goodbye(text):
            self.chat.end_debate()
            last = "Okay."
            self._say(last)
            return last, tool, False
        bye = dismissal_reply(text)
        if bye is not None:
            logging.getLogger("red.commands").info("%r -> dismissed", text)
            self._say(bye)
            return bye, tool, False
        named = self.chat.take_name(text)          # "call me Ari" (red/memory.py)
        if named is not None:
            logging.getLogger("red.commands").info("%r -> name", text)
            self._say(named)
            return named, tool, False
        stopped = self._stop_own_song(text)
        if stopped is not None:                    # "stop" after a song Red put on by itself
            logging.getLogger("red.commands").info("%r -> stop the idle song", text)
            self._say(stopped)
            return stopped, tool, False
        switched = companions.handle_switch(text, self.settings.home)   # "switch to Remy"
        if switched is not None:
            logging.getLogger("red.commands").info("%r -> switch companion", text)
            self.chat.remember(text, switched)
            self._say(switched)
            return switched, tool, False
        quick = quick_reply(text, name=self.chat.user_name())
        if quick is not None:
            logging.getLogger("red.commands").info("%r -> small talk", text)
            self.chat.remember(text, quick)
            self._say(quick)
            return quick, tool, asks_back(quick)
        self._state("thinking", f"“{text}”")
        try:
            if talk_only(text, tool, self.settings):
                # Plain talk: straight to the chat, no router call first (red/gate.py).
                steps = [(text, Router.talk_route())]
                timer.mark("gate")
            else:
                steps = self.router.route_many(text, context=self.chat.history(CONTEXT_LINES))
                timer.mark("route")
        except (RouteError, LLMError) as e:
            log.warning("Couldn't route %r: %s", text, e)
            last = "Sorry, I didn't understand that. Could you say it another way?"
            self._say(last)
            return last, tool, True
        if len(steps) > 1:
            return self._run_steps(text, steps, timer)
        route = steps[0][1]
        logging.getLogger("red.commands").info("%r -> %s", text, route.to_json())
        tool = route.tool
        if tool == "check_repos":
            self._state("thinking", "Checking your repos...")
        # Answers and chat are spoken sentence by sentence while the model
        # writes them (red/speech.py); actions just return their reply.
        stream = SpeechStream(self.voice.speaker, on_text=self._speaking)
        self._stream = stream
        try:
            with speaking_to(stream):
                last = self.executor.execute(text, route, talk=self._talk)
            question = ""
            if route.is_none:
                timer.mark("chat")
                again = True
            else:
                timer.mark("act")
                self.chat.remember(text, last)
                if tool in INFO_TOOLS and self.executor.last_status == "ok":
                    # An answer: ask if they want more, and listen for it.
                    question = self._follow_up_question(last)
                    last = f"{last.rstrip()} {question}" if question else last
                    again = True
                else:
                    # Done is done: after an action Red goes quiet. It keeps listening
                    # only if the reply asks you something or the tool failed.
                    again = asks_back(last) or self.executor.last_status == "error"
            if stream.used:
                self._finish_stream(stream, last, question, timer)
            else:
                timer.first_word()
                self._say(last, self.executor.last_details, meanwhile=self.executor.last_later)
        finally:
            self._allow_interrupt(False)
            self._stream = None
        self.executor.last_later = None
        timer.mark("speak")
        timer.log(text, route.tool)
        if self._interrupted:
            # Cut off by "Hey Red": listen for what you say next, right away.
            self._interrupted = False
            again = True
        return last, tool, again

    def _run_steps(self, text: str, steps, timer):
        """Several commands in one sentence: each in order, checked and confirmed like one.

        Stops at the first one that fails or that you say no to, and says which.
        """
        done: list[tuple[str, str, str]] = []
        laters = []
        for part, route in steps:
            logging.getLogger("red.commands").info("%r -> %s", part, route.to_json())
            self._state("thinking", f"“{part}”")
            reply = self.executor.execute(part, route, talk=self._talk)
            status = self.executor.last_status
            if self.executor.last_later is not None:
                laters.append(self.executor.last_later)
                self.executor.last_later = None
            done.append((part, reply, status))
            if status in ("error", "cancelled"):
                break
            self.chat.remember(part, reply)
        timer.mark("act")
        last = steps_reply(done, len(steps))
        tools = [route.tool for _, route in steps[:len(done)]]
        failed = done[-1][2] == "error"
        again = failed or asks_back(last)
        if not failed and done[-1][2] != "cancelled" and any(t in INFO_TOOLS for t in tools):
            question = self._follow_up_question(last)
            last = f"{last} {question}" if question else last
            again = True

        def meanwhile():
            for later in laters:          # bring each opened window to the front, in order
                run_later(later)
        timer.first_word()
        self._say(last, self.executor.last_details, meanwhile=meanwhile if laters else None)
        timer.mark("speak")
        timer.log(text, "+".join(tools))
        return last, tools[-1], again

    # --- helpers -------------------------------------------------------------

    def _stop_own_song(self, text: str) -> str | None:
        idle = getattr(self, "idle", None)
        if idle is None:
            return None
        return idle.stop_reply(text, lambda: self.executor.registry.get("stop_music").run())

    def _prime_chat(self) -> None:
        """Red just woke: let the model read the chat prompt (and load, if it was unloaded)
        while you talk, so the reply only has your words left to read. At most once a minute."""
        if not getattr(self.settings, "chat_first", False) or self.chat is None:
            return
        now = time.monotonic()
        if now - getattr(self, "_primed_at", -PRIME_EVERY_SECONDS) < PRIME_EVERY_SECONDS:
            return
        self._primed_at = now
        threading.Thread(target=self.chat.prime, name="red-prime", daemon=True).start()

    def _follow_up_question(self, answer: str) -> str:
        """'Anything more you want to know about it?', or "" when the answer already asks something."""
        if asks_back(answer) or self.settings.follow_up_seconds <= 0 or self.chat.is_debate:
            return ""
        question = FOLLOW_UP_QUESTIONS[self._next_question % len(FOLLOW_UP_QUESTIONS)]
        self._next_question += 1
        return question

    def _speaking(self, text: str) -> None:
        """The first streamed sentence is on its way: show it, and let you cut in."""
        self._allow_interrupt(True)
        self._state("speaking", text)

    def _finish_stream(self, stream: SpeechStream, last: str, question: str, timer) -> None:
        """The answer is (being) spoken already: add the follow-up question, then wait."""
        self.out(f"Red: {last}")
        for line in self.executor.last_details.splitlines():
            self.out(f"     {line}")
        if self.executor.last_status == "error" and not stream.cancelled:
            stream.say(last)                  # it broke off part way: say why
        elif question and not stream.cancelled:
            stream.say(question)
        self._state("speaking", f"{last}\n{self.executor.last_details}".strip())
        stream.finish(timeout=120)
        timer.first_word(stream.first_word_at)

    def _talk(self, said: str, fallback: str) -> str:
        """Not a command: talk like a friend instead of the router's stock line."""
        self._state("thinking", "")
        return self.chat.reply(said, fallback=fallback)

    def _state(self, state: str, text: str = "") -> None:
        try:
            self.overlay.set_state(state, text)
        except Exception:  # noqa: BLE001 - the overlay is only a display
            log.exception("Overlay update failed")
        events.emit("state", name=state, text=text)

    def _speak(self, text: str, interruptible: bool = False) -> None:
        if interruptible:
            self._allow_interrupt(True)
        try:
            events.emit("said", text=text)          # a whole reply: shown as it starts
            self.voice.speaker.say(text, block=True)
        except Exception:  # noqa: BLE001 - no speakers: the text is still shown
            log.exception("Couldn't speak")
        finally:
            if interruptible:
                self._allow_interrupt(False)

    def _say(self, reply: str, details: str = "", meanwhile: Callable[[], object] | None = None) -> None:
        """Show and speak `reply`. `meanwhile` (a tool's follow-through) runs while Red speaks."""
        self.out(f"Red: {reply}")
        for line in details.splitlines():
            self.out(f"     {line}")
        self._state("speaking", f"{reply}\n{details}".strip())
        worker = None
        if meanwhile is not None:
            worker = threading.Thread(target=run_later, args=(meanwhile,), name="red-later", daemon=True)
            worker.start()
        self._speak(reply, interruptible=True)
        if worker is not None:
            worker.join(LATER_WAIT_SECONDS)



class Timing:
    """How long each step of one command took, for red.log (task: make Red faster).

    "After you stopped" counts from the end of your speech: the pause Red
    waited (and the pause check, if one ran) is taken off the recording time.
    """

    def __init__(self, settings: Settings, clock: Callable[[], float] = time.perf_counter):
        self._settings, self._clock = settings, clock
        self.start = self._last = clock()
        self.speech_end = self.start
        self.pause = 0.0
        self.text_ready: float | None = None      # seconds after you stopped that the text was ready
        self.steps: list[tuple[str, float]] = []
        self.done_at: dict[str, float] = {}

    def recorded(self, quick: bool, check_seconds: float = 0.0, stats: dict | None = None) -> None:
        """The recording ended. `stats` (from record_command) has the pause it really waited."""
        now = self._clock()
        s = self._settings
        self.pause = (s.quick_end_silence_seconds + check_seconds) if quick else s.end_silence_seconds
        if stats and stats.get("quiet"):
            self.pause = stats["quiet"]
        self.text_ready = stats.get("ready") if stats else None
        self.speech_end = max(self.start, now - self.pause)
        self.steps.append(("listen", now - self.start))
        self._last = now

    def mark(self, step: str) -> None:
        now = self._clock()
        self.steps.append((step, now - self._last))
        self.done_at[step] = now - self.speech_end
        self._last = now

    def first_word(self, at: float | None = None) -> None:
        """When Red started speaking (a streamed answer's first sentence, or the reply)."""
        at = self._clock() if at is None else at
        self.done_at["first word"] = at - self.speech_end

    def summary(self, text: str, tool: str) -> str:
        steps = ", ".join(f"{name} {secs:.2f} s" for name, secs in self.steps)
        done = self.done_at.get("act", self.done_at.get("chat"))
        tail = f"; done {done:.2f} s after you stopped" if done is not None else ""
        first = self.done_at.get("first word")
        tail += f", first word at {first:.2f} s" if first is not None else ""
        spoken = self.done_at.get("speak")
        tail += f", reply spoken by {spoken:.2f} s" if spoken is not None else ""
        ready = f", text ready {self.text_ready:.2f} s after you stopped" if self.text_ready is not None else ""
        return f"Timing {text[:60]!r} -> {tool}: {steps} (pause waited {self.pause:.2f} s{ready}){tail}"

    def log(self, text: str, tool: str) -> None:
        log.info(self.summary(text, tool))


def talk_only(text: str, last_tool: str | None, settings: Settings) -> bool:
    """True when `text` is plain talk that can skip the router (red/gate.py).

    Not right after a tool: "Blink Crazy by Lisa" after "which song?" or a spelled
    name after "call me ..." are answers to it, and only the router knows that.
    """
    if not getattr(settings, "chat_first", False) or last_tool not in (None, "none"):
        return False
    from .gate import needs_router
    return not needs_router(text)


def asks_back(reply: str) -> bool:
    """True when Red's reply asks the user something, so Red should listen for the answer."""
    return reply.rstrip().rstrip("\"'”’)").endswith("?")


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


def _keep_alive_is_zero(keep_alive: str) -> bool:
    """RED_LLM_KEEP_ALIVE=0 means "unload right away", so don't keep the model warm."""
    return keep_alive.strip().lower() in {"0", "0s", "0m", "0h"}


RESUME_CHECK_SECONDS = 15.0
PRIME_EVERY_SECONDS = 60.0          # the chat prompt is read ahead when Red wakes, at most this often


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
                    log.info("Startup: the model is loaded and warm, %.1f s after Red started",
                             since_start())
            except Exception as e:  # noqa: BLE001 - a slow first command is the only cost
                log.warning("Couldn't load the model ahead of time: %s", e)
            # Wait by the wall clock, in short steps: after the laptop sleeps, Ollama has
            # unloaded the model (its keep_alive ran out) while a plain wait(every) could
            # still have minutes to go. On 2026-11-13 the first "You're crazy!" after a
            # sleep spent 23 s loading. Now the model is back within RESUME_CHECK seconds.
            due = time.time() + every
            while time.time() < due:
                if stop.wait(min(RESUME_CHECK_SECONDS, every)):
                    return
            if time.time() - due > RESUME_CHECK_SECONDS * 2:
                log.info("Woke up after %.0f s away: loading the model again", time.time() - due)

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
        t0 = time.perf_counter()
        voice.transcriber.load()
        t1 = time.perf_counter()
        voice.speaker.load()
        log.info("Startup: speech models loaded (Whisper %.1f s, voice %.1f s), %.1f s after Red "
                 "started", t1 - t0, time.perf_counter() - t1, since_start())
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
        attach = getattr(overlay, "attach_speaker", None)      # the companion's mouth follows the voice
        if attach is not None:
            try:
                attach(voice.speaker)
                overlay.on_click = lambda: app.chat_window.show() if getattr(app, "chat_window", None) else None
                from .avatar import mic_control
                overlay.on_mic = mic_control(lambda: app.listener)       # "Microphone off" in the menu
                from .avatar.wiring import wire_menu
                wire_menu(overlay, app)                                  # talk, reminders, tasks, music...
            except Exception:  # noqa: BLE001 - the companion is only a display
                log.exception("Couldn't connect the companion to the voice")
        app.run(stop)

    try:
        code = run_with_overlay(worker, style=settings.overlay, settings=settings)
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
    try:
        from .plugins import install_examples
        print(f"Example plugins are in {install_examples(settings.home)}.")
    except OSError as e:
        print(f"Couldn't copy the example plugins: {e}")


EXAMPLE_ENV = REPO_ROOT / ".env.example"


def with_settings(text: str, values: dict[str, str]) -> str:
    """.env text with each `KEY=` line set to values[KEY] (other lines untouched)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in values:
            lines[i] = f"{key}={values[key]}"
    return "\n".join(lines) + "\n"


def _setup_model(settings: Settings, detect: Callable | None = None) -> Settings:
    """Pick a starting model for this PC's GPU and RAM (red.hardware).

    A new RED_HOME\\config\\.env gets it written in. An existing .env is
    never changed: Red only says what it would pick.
    """
    from .hardware import detect as detect_hardware
    from .llm import MODELS

    choice = (detect or detect_hardware)()
    best = MODELS[choice.model].best_for if choice.model in MODELS else ""
    print(f"This PC has {choice.why}. Best fit: {choice.model} ({best}), "
          f"Whisper {choice.whisper_model} on the {choice.whisper_device.upper()}.")
    env = settings.config_dir / ".env"
    if env.exists() or not EXAMPLE_ENV.is_file():
        if settings.llm_model != choice.model:
            print(f"Your settings use {settings.llm_model}. To switch, set "
                  f"RED_LLM_MODEL={choice.model} in {env}.")
        return settings
    values = {"RED_LLM_MODEL": choice.model, "RED_WHISPER_MODEL": choice.whisper_model,
              "RED_WHISPER_DEVICE": choice.whisper_device}
    env.write_text(with_settings(EXAMPLE_ENV.read_text(encoding="utf-8"), values), encoding="utf-8")
    print(f"Created {env} with these. Change them there any time.")
    return load_settings(settings.home)


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


def _setup_web_search(settings: Settings) -> None:
    """Install Red's own SearXNG, so look_up can check web pages. Optional: a
    failure is reported and Red works without it (Wikipedia only)."""
    if not settings.web_search:
        print("Web search is off (RED_WEB_SEARCH=off), so SearXNG isn't installed.")
        return
    from subprocess import CalledProcessError

    from .downloads import DownloadError
    from .searxng import SearxngError, install
    try:
        install(settings)
    except (DownloadError, SearxngError, CalledProcessError, OSError) as e:
        log.warning("SearXNG install failed: %s", e)
        print(f"Web search couldn't be installed ({e}). Red works without it, answering from "
              "Wikipedia. Run python -m red setup again to retry.")


def _google_command(cmd: str, settings: Settings) -> int:
    from .google_auth import GoogleError, login, logout
    restart = "Restart Red to use it: python -m red stop, then python -m red background."
    try:
        if cmd == "google-login":
            path = login(settings.home)
            print(f"Signed in. The token is in {path} (only on this PC). {restart}")
        elif logout(settings.home):
            print(f"Signed out of Google, and the token is deleted. {restart}")
        else:
            print("Red wasn't signed in to Google.")
    except GoogleError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
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
    sub.add_parser("app", help="open the setup and settings window")
    p_wake = sub.add_parser("wake-test", help="see what the wake word hears from your microphone")
    wake_mode = p_wake.add_mutually_exclusive_group()
    wake_mode.add_argument("--record", action="store_true",
                           help="record your own \"Hey Red\" takes and normal talk (about 5 minutes)")
    wake_mode.add_argument("--replay", action="store_true",
                           help="score the wake word on those recordings, offline")
    wake_mode.add_argument("--learn", action="store_true",
                           help="learn how Whisper hears your \"Hey Red\" from those recordings")
    sub.add_parser("voice-setup", help="say \"Hey Red\" a few times so Red learns your voice")
    sub.add_parser("google-login", help="optional: let Red use your Gmail, Calendar and Contacts")
    sub.add_parser("google-logout", help="sign Red out of Google")
    for name, text in (("background", "run Red with no window"),
                       ("hotkey", "watch for Ctrl+Alt+R and start Red when it isn't running"),
                       ("stop", "stop the hidden Red"), ("status", "is the hidden Red running?")):
        sub.add_parser(name, help=text)
    p_plugins = sub.add_parser("plugins", help="list plugins, or turn one on or off")
    p_plugins.add_argument("action", nargs="*", metavar="list | on NAME | off NAME")
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

    if args.cmd == "app":
        from . import app as app_mod
        return app_mod.main(load_settings())

    settings = load_settings()
    settings.ensure_dirs()
    if args.cmd == "wake-test":
        logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s")
        from .wake_test import main as wake_test_main
        return wake_test_main(settings, "record" if args.record else "replay" if args.replay
                              else "learn" if args.learn else "live")
    if args.cmd == "voice-setup":
        logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                            format="%(asctime)s %(name)s %(levelname)s %(message)s")
        from .voice_setup import main as voice_setup_main
        return voice_setup_main(settings)
    if args.cmd in ("background", "hotkey", "stop", "status"):
        if args.cmd == "hotkey":         # the watchdog's restarts go to red.log
            logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                                format="%(asctime)s %(name)s %(levelname)s %(message)s")
        from .background import main as background_main
        return background_main(args.cmd, settings.home, hotkey=settings.hotkey)
    if args.cmd == "plugins":
        from .plugins import main as plugins_main
        return plugins_main(settings.home, args.action)
    if args.cmd == "startup":
        from .startup import main as startup_main
        return startup_main(args.action, settings.home)
    if args.cmd in ("google-login", "google-logout"):
        return _google_command(args.cmd, settings)
    logging.basicConfig(filename=settings.logs_dir / "red.log", level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.cmd == "setup":
        settings.ensure_dirs()
        settings = _setup_model(settings)
        _install_examples(settings)
    _check_allowlist(settings)

    print("Starting the local model...", file=sys.stderr)
    try:
        llm, server = connect(settings)
    except LLMError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    web = None
    if args.cmd is None and not args.dry_run:
        # Voice, background and typed mode: Red's own SearXNG, started in the
        # background so it never slows Red's start (red/searxng.py).
        from .searxng import WebSearch
        web = WebSearch(settings)
        web.begin()
    try:
        if args.cmd == "setup":
            print(f"Ready: {type(llm).__name__} with model {settings.llm_model}")
            if server:
                server.stop()
                server = None
            code = _setup_voice(settings)
            _setup_web_search(settings)
            return code
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
            chat = make_chat(router.llm, settings)
            bind_conversation(registry, chat)
            try:
                _typed_loop(lambda c: _run(router, executor, c, chat), "Red. Type a command, or 'quit'.")
            finally:
                if reminders is not None and reminders.on_due is _print_reminder:
                    reminders.on_due = None
            return 0
        return _voice_mode(settings, router, registry)
    finally:
        if web is not None:
            web.stop()
        if server:
            server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
