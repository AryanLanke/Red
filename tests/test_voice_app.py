"""The voice loop in red.__main__ with fakes: no microphone, models, speakers, hotkey hook or Qt."""

import contextlib
import json
import threading
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakeAsk, FakeRunner, FakeStartfile
from red import __main__ as cli
from red.allowlist import Allowlist
from red.config import load_settings
from red.router import Router
from red.tools.base import Tool, ToolRegistry
from red.tools.system import CancelShutdown, OpenFolder, Shutdown

NOW = datetime(2026, 11, 8, 21, 40)


class Audio:
    def __init__(self, size):
        self.size = size


class FakeTranscriber:
    device, compute_type = "cpu", "int8"

    def __init__(self, *texts, error=None):
        self.texts, self.error, self.loaded = list(texts), error, False

    def transcribe(self, audio):
        if self.error:
            raise self.error
        return self.texts.pop(0)

    def load(self):
        self.loaded = True


class FakeSpeaker:
    def __init__(self):
        self.said, self.stopped = [], False

    def say(self, text, block=True):
        self.said.append(text)

    def load(self):
        pass

    def stop(self):
        self.stopped = True


class FakeListener:
    instances = []

    def __init__(self, on_trigger, hotkey, wakeword=None, *, model_dir=None, threshold=0.5,
                 fail_wakeword=False):
        if wakeword and fail_wakeword:
            raise ValueError(f"Unknown wake word {wakeword!r}")
        self.on_trigger, self.hotkey, self.wakeword = on_trigger, hotkey, wakeword
        self.model_dir, self.threshold = model_dir, threshold
        self.started = self.stopped = False
        FakeListener.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    @contextlib.contextmanager
    def paused_while(self):
        self.pauses = getattr(self, "pauses", 0) + 1
        yield

    def allow_interrupt(self, on):
        self.interrupt_calls = getattr(self, "interrupt_calls", []) + [on]


class FakeOverlay:
    def __init__(self):
        self.states = []

    def set_state(self, state, text=""):
        self.states.append((state, text))

    @property
    def names(self):
        return [s for s, _ in self.states]


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = replies

    def complete_json(self, system, user, schema):
        reply = self.replies[user.rsplit("\nCommand: ", 1)[-1]]   # without the conversation
        if isinstance(reply, Exception):
            raise reply
        return json.dumps(reply)


class FakeRepos(Tool):
    name = "check_repos"
    description = "Check repos"
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}
    last_details = ""

    def run(self):
        self.last_details = "red: 2 unpushed commits\nnotes: clean"
        return "1 of 2 repos needs attention."


class FakeStopMusic(Tool):
    name = "stop_music"
    description = "Stop music"
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self):
        return "Stopped the music."


COMMANDS = {
    "Open my downloads.": {"tool": "open_folder", "args": {"folder": "Downloads"}},
    "Shut down in 2 hours.": {"tool": "shutdown", "args": {"minutes": 120}},
    "Check my repos.": {"tool": "check_repos", "args": {}},
    "Stop the music.": {"tool": "stop_music", "args": {}},
    "Banana.": {"tool": "none", "args": {"reply": "What should I do?"}},
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    for name in ("RED_HOTKEY", "RED_WAKEWORD", "RED_WAKEWORD_THRESHOLD", "RED_WHISPER_DEVICE",
                 "RED_WHISPER_MODEL", "RED_PIPER_VOICE", "RED_MIC_DEVICE",
                 "RED_LLM_URL", "RED_LLM_BACKEND", "RED_LLM_GPU", "RED_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RED_FOLLOW_UP_SECONDS", "0")   # one exchange per trigger, unless a test asks
    FakeListener.instances = []
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    runner, start = FakeRunner(codes={"/a": 1116}), FakeStartfile()
    registry = ToolRegistry([
        OpenFolder(allowlist=Allowlist(), startfile=start, known=lambda: {"downloads": downloads}),
        Shutdown(runner=runner, now=lambda: NOW), CancelShutdown(runner=runner),
        FakeRepos(), FakeStopMusic()])
    return {"settings": load_settings(tmp_path), "registry": registry, "runner": runner,
            "start": start, "llm": ScriptedLLM(COMMANDS), "home": tmp_path}


def make_app(world, *texts, answers=("no",), audio_size=16000, ask_error=None, typed=None,
             transcriber=None, fail_wakeword=False, settings=None,
             attach=lambda on_due: None):
    speaker = FakeSpeaker()
    spoken = FakeAsk(*answers)
    asked = []

    def make_ask(spk, trn):
        assert spk is speaker
        def ask(q, t):
            asked.append(q)
            if ask_error:
                raise ask_error
            return spoken(q, t)
        return ask

    voice = cli.Voice(
        transcriber=transcriber or FakeTranscriber(*texts),
        speaker=speaker,
        record=lambda **kw: Audio(audio_size),
        chime=lambda: None,
        listener_factory=lambda *a, **k: FakeListener(*a, fail_wakeword=fail_wakeword, **k),
        make_ask=make_ask,
    )
    overlay = FakeOverlay()
    out = []
    app = cli.VoiceApp(settings or world["settings"], Router(world["registry"], world["llm"]),
                       world["registry"], voice, overlay, typed_fallback=typed or FakeAsk(),
                       log_path=world["home"] / "commands.jsonl",
                       out=out.append, attach=attach)
    return app, speaker, overlay, asked, out


def log_lines(world):
    path = world["home"] / "commands.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]


def test_command_flow_states_and_reply(world):
    app, speaker, overlay, asked, out = make_app(world, "Open my downloads.")
    app.handle("hotkey")
    assert speaker.said == ["Opening Downloads."]
    assert overlay.names == ["listening", "thinking", "thinking", "speaking", "idle"]
    assert overlay.states[2] == ("thinking", "\u201cOpen my downloads.\u201d")
    assert overlay.states[-1] == ("idle", "Opening Downloads.")
    assert "You said: Open my downloads." in out
    assert len(world["start"].calls) == 1 and asked == []
    assert log_lines(world)[0]["command"] == "Open my downloads."


@pytest.mark.parametrize("answer, ran", [("Yes.", True), ("No.", False), (None, False),
                                         ("yes please", True), ("Yeah, go ahead.", True),
                                         ("okay", False), ("Yes, no, wait.", False)])
def test_destructive_asks_aloud(world, answer, ran):
    app, speaker, overlay, asked, _ = make_app(world, "Shut down in 2 hours.", answers=[answer])
    app.handle("wakeword")
    assert asked == ["Shut down in 2 hours (at 11:40 PM)?"]
    assert ("confirm", "Shut down in 2 hours (at 11:40 PM)?") in overlay.states
    if ran:
        assert world["runner"].flags == [["/a"], ["/s", "/t", "7200"]]
        assert "11:40 PM" in speaker.said[-1]
    else:
        assert world["runner"].calls == []
        assert speaker.said[-1] in ("Cancelled.", "No answer, so I cancelled it.")


def test_spoken_confirm_failure_falls_back_to_typed(world):
    typed = FakeAsk("y")
    app, speaker, _, asked, _ = make_app(world, "Shut down in 2 hours.",
                                         ask_error=OSError("no microphone"), typed=typed)
    app.handle("hotkey")
    assert typed.questions == [("Shut down in 2 hours (at 11:40 PM)?", 30.0)]
    assert world["runner"].flags[-1] == ["/s", "/t", "7200"]


def test_cancel_never_asks(world):
    world["llm"].replies["Cancel it."] = {"tool": "cancel_shutdown", "args": {}}
    app, speaker, _, asked, _ = make_app(world, "Cancel it.")
    app.handle("hotkey")
    assert asked == [] and world["runner"].flags == [["/a"]]
    assert "Nothing was scheduled" in speaker.said[-1]


def test_silence_and_empty_transcript(world):
    app, speaker, overlay, _, _ = make_app(world, audio_size=0)
    app.handle("hotkey")
    assert speaker.said == ["I didn't hear anything."] and overlay.names[-1] == "idle"
    app, speaker, _, _, _ = make_app(world, "  ")
    app.handle("hotkey")
    assert speaker.said == ["Sorry, I didn't catch that."]


def test_route_error_and_none(world):
    from red.llm import LLMError
    world["llm"].replies["Banana split."] = LLMError("server down")
    app, speaker, _, _, _ = make_app(world, "Banana split.", "Banana.")
    app.handle("hotkey")
    app.handle("hotkey")
    assert speaker.said == ["Sorry, I didn't understand that.", "What should I do?"]


def test_crash_in_one_command_is_reported_and_red_keeps_going(world):
    app, speaker, overlay, _, _ = make_app(world, transcriber=FakeTranscriber(error=RuntimeError("bad")))
    app.handle("hotkey")
    assert "error" in overlay.names and overlay.names[-1] == "idle"
    assert speaker.said == ["Sorry, something went wrong."]


def test_repo_details_go_to_overlay_and_log(world):
    app, speaker, overlay, _, out = make_app(world, "Check my repos.")
    app.handle("hotkey")
    assert ("thinking", "Checking your repos...") in overlay.states
    speaking = [t for s, t in overlay.states if s == "speaking"][0]
    assert speaking.startswith("1 of 2 repos needs attention.") and "red: 2 unpushed" in speaking
    assert speaker.said == ["1 of 2 repos needs attention."]   # details are shown, not spoken
    assert log_lines(world)[0]["details"] == "red: 2 unpushed commits\nnotes: clean"


def test_listener_gets_settings(world):
    app, *_ = make_app(world)
    listener = app.start_listener()
    assert listener.started and listener.hotkey == "<ctrl>+<alt>+r"
    assert listener.wakeword == "hey_red" and listener.threshold == 0.5
    assert listener.model_dir == world["home"] / "models" / "wakeword"
    assert app.notice == ""
    assert app.ready_text() == 'Press Ctrl+Alt+R or say "Hey Red", then speak.'


def test_wakeword_failure_means_hotkey_only(world):
    app, *_ = make_app(world, fail_wakeword=True)
    listener = app.start_listener()
    assert listener.started and listener.wakeword is None and listener.hotkey
    assert "Hey Red" in app.notice and "only the hotkey" in app.notice
    assert app.ready_text() == "Press Ctrl+Alt+R, then speak."


def test_nothing_can_trigger(world, monkeypatch):
    monkeypatch.setenv("RED_HOTKEY", "off")
    settings = load_settings(world["home"])
    app, *_ = make_app(world, fail_wakeword=True, settings=settings)
    with pytest.raises(RuntimeError, match="hotkey is off"):
        app.start_listener()


def test_run_starts_and_stops_everything(world):
    app, speaker, overlay, _, out = make_app(world)
    stop = threading.Event()
    stop.set()
    app.run(stop)
    listener = FakeListener.instances[-1]
    assert listener.started and listener.stopped and speaker.stopped
    assert overlay.states[0][0] == "idle" and "Hey Red" in overlay.states[0][1]
    assert any(line.startswith("Ready.") for line in out)


# ---------- main() in voice mode ----------

def test_main_voice_mode_end_to_end(world, monkeypatch, capsys):
    monkeypatch.setenv("RED_HOME", str(world["home"]))
    monkeypatch.setattr(cli, "default_registry", lambda: world["registry"])
    monkeypatch.setattr(cli, "connect", lambda settings: (world["llm"], None))
    speaker = FakeSpeaker()
    transcriber = FakeTranscriber("Open my downloads.")
    voice = cli.Voice(transcriber=transcriber, speaker=speaker, record=lambda **kw: Audio(8000),
                      chime=lambda: None, listener_factory=FakeListener,
                      make_ask=lambda s, t: FakeAsk("no"))
    monkeypatch.setattr(cli, "load_voice", lambda settings: voice)
    monkeypatch.setattr(cli, "attach_reminders", lambda on_due: None)
    overlay = FakeOverlay()

    def fake_run_with_overlay(worker, style="card"):
        assert style == "glow"   # the default look
        thread = threading.Thread(target=worker, args=(overlay,), daemon=True)
        thread.start()
        for _ in range(200):
            if FakeListener.instances and FakeListener.instances[-1].started:
                break
            threading.Event().wait(0.01)
        FakeListener.instances[-1].on_trigger("hotkey")
        return 130                                   # as if Ctrl+C was pressed

    import red.overlay
    monkeypatch.setattr(red.overlay, "run_with_overlay", fake_run_with_overlay)
    assert cli.main([]) == 0
    assert transcriber.loaded
    assert speaker.said == ["Opening Downloads."] and speaker.stopped
    assert len(world["start"].calls) == 1
    assert FakeListener.instances[-1].stopped
    assert "Bye." in capsys.readouterr().out


def test_main_voice_mode_without_voice_packages(world, monkeypatch, capsys):
    monkeypatch.setenv("RED_HOME", str(world["home"]))
    monkeypatch.setattr(cli, "connect", lambda settings: (world["llm"], None))

    def missing(settings):
        raise ImportError("No module named 'numpy'")
    monkeypatch.setattr(cli, "load_voice", missing)
    assert cli.main([]) == 2
    assert "--typed" in capsys.readouterr().err


@pytest.mark.parametrize("hotkey, text", [("<ctrl>+<alt>+r", "Ctrl+Alt+R"),
                                          ("<ctrl>+<shift>+<space>", "Ctrl+Shift+Space")])
def test_pretty_hotkey(hotkey, text):
    assert cli.pretty_hotkey(hotkey) == text


def test_pretty_wakeword():
    assert cli.pretty_wakeword("hey_red") == "Hey Red"
    assert cli.pretty_wakeword("D:\\models\\hey_red_v0.1.onnx") == "Hey Red"


def test_small_talk_is_answered_without_the_model(world):
    app, speaker, overlay, asked, out = make_app(world, "Thanks, Red.")
    app.handle("wakeword")
    assert speaker.said == ["You're welcome!"]
    # "thinking" once while Whisper transcribes, then straight to the answer:
    # no second "thinking" while the model works.
    assert overlay.names == ["listening", "thinking", "speaking", "idle"]
    # ScriptedLLM has no reply for this sentence and would raise if asked.
    assert "Sorry, something went wrong." not in speaker.said
    assert asked == []


# --- follow-up conversation ----------------------------------------------------

class SilentThenWords:
    """record(): speech for the first n calls, then silence (an empty array)."""

    def __init__(self, speech_calls):
        self.speech_calls = speech_calls
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        return Audio(16000 if len(self.calls) <= self.speech_calls else 0)

    @property
    def timeouts(self):
        """The calls without the pause check (VoiceApp always passes one)."""
        return [{k: v for k, v in kw.items() if k != "is_complete"} for kw in self.calls]


def follow_app(world, monkeypatch, *texts, speech_calls=None, **kw):
    monkeypatch.setenv("RED_FOLLOW_UP_SECONDS", "7")
    app, speaker, overlay, asked, out = make_app(world, *texts,
                                                 settings=load_settings(world["home"]), **kw)
    record = SilentThenWords(speech_calls if speech_calls is not None else len(texts))
    app.voice.record = record
    return app, speaker, overlay, record, out


def test_an_action_ends_the_conversation(world, monkeypatch):
    # Do it, then go quiet: no "Anything else?", no second recording.
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Open my downloads.")
    app.handle("wakeword")
    assert speaker.said == ["Opening Downloads."]
    assert record.timeouts == [{}]
    assert overlay.names[-1] == "idle"


def test_chat_keeps_listening_and_stops_on_silence(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Banana.")
    app.handle("wakeword")
    assert len(speaker.said) == 1                            # the reply, nothing on top
    assert record.timeouts == [{}, {"start_timeout": 7.0}]   # the follow-up waits 7 s for you
    assert overlay.names[-1] == "idle"


def test_says_no_and_red_stops(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Banana.", "No, that's all.")
    app.handle("wakeword")
    assert speaker.said[-1] == "Okay."
    assert len(record.calls) == 2


def test_a_command_after_chat_runs_and_then_red_goes_quiet(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(
        world, monkeypatch, "Hello.", "Open my downloads.", "Check my repos.")
    app.handle("hotkey")
    assert speaker.said[0].endswith("What can I do for you?")
    assert speaker.said[1:] == ["Opening Downloads."]
    assert len(record.calls) == 2                            # "Check my repos." is never heard
    assert len(world["start"].calls) == 1


class Broken(Tool):
    name = "open_app"
    description = "Open an app"
    args_schema = {"type": "object", "properties": {"app": {"type": "string"}}, "additionalProperties": False}

    def run(self, app):
        from red.tools.base import ToolError
        raise ToolError(f"I couldn't find an app called {app}.")


def test_a_failure_keeps_listening_so_you_can_say_it_again(world, monkeypatch):
    world["registry"].add(Broken())
    world["llm"].replies["Open Spotfy."] = {"tool": "open_app", "args": {"app": "Spotfy"}}
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Open Spotfy.", "Open my downloads.")
    app.handle("wakeword")
    assert speaker.said == ["I couldn't find an app called Spotfy.", "Opening Downloads."]
    assert len(record.calls) == 2


class Launcher(Tool):
    """Starts something at once and leaves the slow part (bringing it to the front) for later."""
    name = "open_app"
    description = "Open an app"
    args_schema = {"type": "object", "properties": {"app": {"type": "string"}}, "additionalProperties": False}

    def __init__(self, events):
        self.events = events

    def run(self, app):
        self.events.append("launched")
        self.finish_later(lambda: self.events.append("brought to the front"))
        return f"Opening {app}."


def test_the_reply_is_spoken_while_the_follow_through_runs(world, monkeypatch):
    events = []
    world["registry"].add(Launcher(events))
    world["llm"].replies["Open Edge."] = {"tool": "open_app", "args": {"app": "Edge"}}
    app, speaker, *_ = make_app(world, "Open Edge.")
    speaker.say = lambda text, block=True: (events.append(f"said {text}"), speaker.said.append(text))
    app.handle("wakeword")
    assert events[0] == "launched"                      # launched before Red speaks
    assert sorted(events[1:]) == ["brought to the front", "said Opening Edge."]
    assert app.executor.last_later is None


def test_a_failing_follow_through_is_only_logged(world, monkeypatch):
    class Flaky(Launcher):
        def run(self, app):
            self.finish_later(lambda: 1 / 0)
            return f"Opening {app}."
    world["registry"].add(Flaky([]))
    world["llm"].replies["Open Edge."] = {"tool": "open_app", "args": {"app": "Edge"}}
    app, speaker, *_ = make_app(world, "Open Edge.")
    app.handle("wakeword")
    assert speaker.said == ["Opening Edge."]


@pytest.mark.parametrize("reply, asks", [("Done.", False), ("Which one?", True), ('He said "why?"', True),
                                         ("Opening Edge.", False)])
def test_asks_back(reply, asks):
    assert cli.asks_back(reply) is asks


def test_a_question_in_the_reply_is_not_followed_by_another(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Hello.", "No thanks.")
    app.handle("wakeword")
    assert speaker.said[0].endswith("What can I do for you?")
    assert speaker.said[1:] == ["Okay."]


def test_no_follow_up_after_a_failure(world, monkeypatch):
    from red.llm import LLMError
    world["llm"].replies["Banana split."] = LLMError("the model is down")
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Banana split.", speech_calls=1)
    app.handle("wakeword")
    assert speaker.said == ["Sorry, I didn't understand that."]
    assert len(record.calls) == 1


def test_follow_ups_are_capped(world, monkeypatch):
    texts = ["Banana."] * (cli.MAX_FOLLOW_UPS + 1)   # chat keeps the conversation going
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, *texts, speech_calls=99)
    app.handle("wakeword")
    assert len(record.calls) == cli.MAX_FOLLOW_UPS + 1


def test_goodbye_words_are_only_exits_in_a_follow_up(world, monkeypatch):
    # As the first thing you say, "no" is not an exit: it goes to the router.
    world["llm"].replies["No."] = {"tool": "none", "args": {"reply": "Okay, what would you like?"}}
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "No.", speech_calls=1)
    app.handle("wakeword")
    assert speaker.said == ["Okay, what would you like?"]


def test_go_away_ends_the_conversation_at_once(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Fuck off from here.", speech_calls=1)
    app.handle("wakeword")
    assert speaker.said == ["That's not very nice. I'll leave you alone."]
    assert len(record.calls) == 1                     # no "Anything else?"


def test_go_away_in_a_follow_up(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(
        world, monkeypatch, "Banana.", "Just go from here, I don't need your help.")
    app.handle("wakeword")
    assert speaker.said[-1] == 'Okay. Say "Hey Red" when you need me.'
    assert len(record.calls) == 2


# --- the quick end of speech ------------------------------------------------------

class CountingTranscriber(FakeTranscriber):
    def __init__(self, *texts):
        super().__init__(*texts)
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return super().transcribe(audio)


def test_the_pause_check_transcript_is_used_once(world, caplog):
    transcriber = CountingTranscriber("Open my downloads.")
    app, speaker, *_ = make_app(world, transcriber=transcriber)
    clip = Audio(16000)

    def record(**kw):
        assert kw["is_complete"](clip) is True      # "Open my downloads." sounds finished
        return clip
    app.voice.record = record
    with caplog.at_level("INFO", logger="red"):
        app.handle("wakeword")
    assert speaker.said == ["Opening Downloads."]
    assert transcriber.calls == 1                    # not transcribed a second time
    assert any("Timing 'Open my downloads.' -> open_folder" in r.message for r in caplog.records)


def test_an_unfinished_pause_check_is_transcribed_again(world):
    transcriber = CountingTranscriber("Open my", "Open my downloads.")
    app, speaker, *_ = make_app(world, transcriber=transcriber)

    def record(**kw):
        assert kw["is_complete"](Audio(8000)) is False    # "Open my": keep listening
        return Audio(16000)                               # more audio came after
    app.voice.record = record
    app.handle("wakeword")
    assert speaker.said == ["Opening Downloads."] and transcriber.calls == 2


def test_filler_runs_nothing_and_listens_once_more(world, monkeypatch):
    # 22:26 in the log: "you know" went to the answer tool.
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "you know", "Open my downloads.")
    app.handle("wakeword")
    assert speaker.said == ["Opening Downloads."]          # nothing said for "you know"
    assert record.timeouts == [{}, {"start_timeout": 7.0}]


def test_filler_in_a_follow_up_just_ends(world, monkeypatch):
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Banana.", "hmm", "Open my downloads.")
    app.handle("wakeword")
    assert len(speaker.said) == 1 and len(record.calls) == 2
    assert world["start"].calls == []


# --- after an answer, ask if they want more (plan.md task 2a) -------------------------

class FakeAnswer(Tool):
    """Stands in for answer: says a fact (or a question back, or fails)."""
    name = "answer"
    description = "Answer a question"
    args_schema = {"type": "object", "properties": {"question": {"type": "string"}},
                   "additionalProperties": False}

    def __init__(self, reply="Mount Everest is 8,849 metres tall."):
        self.reply = reply

    def run(self, question):
        if self.reply is None:
            from red.tools.base import ToolError
            raise ToolError("I couldn't find that.")
        return self.reply


def answer_world(world, reply="Mount Everest is 8,849 metres tall."):
    world["registry"].add(FakeAnswer(reply))
    for said in ("How tall is Everest?", "And K2?", "What about Kangchenjunga?"):
        world["llm"].replies[said] = {"tool": "answer", "args": {"question": said}}


def test_an_answer_asks_if_you_want_more_and_keeps_listening(world, monkeypatch):
    answer_world(world)
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "How tall is Everest?")
    app.handle("wakeword")
    assert speaker.said == ["Mount Everest is 8,849 metres tall. Anything more you want to know about it?"]
    assert record.timeouts == [{}, {"start_timeout": 7.0}]     # listened for the answer, then silence
    assert overlay.names[-1] == "idle"


def test_the_follow_up_question_is_never_the_same_twice_in_a_row(world, monkeypatch):
    answer_world(world)
    app, speaker, overlay, record, out = follow_app(
        world, monkeypatch, "How tall is Everest?", "And K2?", "What about Kangchenjunga?")
    app.handle("wakeword")
    questions = [s.removeprefix("Mount Everest is 8,849 metres tall. ") for s in speaker.said]
    assert len(questions) == 3 and all(q in cli.FOLLOW_UP_QUESTIONS for q in questions)
    assert questions[0] == "Anything more you want to know about it?"
    assert all(a != b for a, b in zip(questions, questions[1:]))


def test_an_answer_that_already_asks_gets_no_second_question(world, monkeypatch):
    answer_world(world, reply="Do you mean the mountain or the film?")
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "How tall is Everest?")
    app.handle("wakeword")
    assert speaker.said == ["Do you mean the mountain or the film?"]
    assert len(record.calls) == 2


@pytest.mark.parametrize("bye", ["No.", "That's it.", "Not really.", "Nope, that's all."])
def test_no_after_the_question_ends_it(world, monkeypatch, bye):
    answer_world(world)
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "How tall is Everest?", bye)
    app.handle("wakeword")
    assert speaker.said[-1] == "Okay."
    assert len(record.calls) == 2


def test_a_failed_answer_has_no_follow_up_question(world, monkeypatch):
    answer_world(world, reply=None)
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "How tall is Everest?")
    app.handle("wakeword")
    assert speaker.said == ["I couldn't find that."]


def test_an_action_still_goes_quiet_after_an_answer(world, monkeypatch):
    answer_world(world)
    app, speaker, overlay, record, out = follow_app(
        world, monkeypatch, "How tall is Everest?", "Open my downloads.", "Check my repos.")
    app.handle("wakeword")
    assert speaker.said[1:] == ["Opening Downloads."]
    assert len(record.calls) == 2                               # "Check my repos." is never heard


def test_the_conversation_remembers_the_answer_without_the_question(world, monkeypatch):
    answer_world(world)
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "How tall is Everest?")
    app.handle("wakeword")
    assert "Anything more" not in app.chat.history(4)


def test_vocabulary_has_apps_and_contacts(world):
    home = world["home"]
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / "allowlist.toml").write_text(
        '[apps]\nspotify = ["spotify.exe"]\n', encoding="utf-8")
    (home / "config" / "contacts.toml").write_text(
        '[contacts]\nrahul = "rahul@example.com"\n', encoding="utf-8")
    words = cli.vocabulary(load_settings(home))
    assert words.startswith("Hey Copilot, Hey Siri, Alexa, OK Google, Gemini, YouTube")
    assert "Spotify" in words and "Rahul" in words


def test_a_broken_allowlist_still_gives_a_vocabulary(world):
    home = world["home"]
    (home / "config").mkdir(exist_ok=True)
    (home / "config" / "allowlist.toml").write_text("[apps\n", encoding="utf-8")
    assert cli.vocabulary(load_settings(home)).startswith("Hey Copilot")


# --- speak while the model writes; "Hey Red" cuts in (plan.md task 6) -----------------

class StreamingLLM:
    """Writes {"answer": "..."} a few characters at a time, and can wait for Red to speak."""

    def __init__(self, answer, wait_for=None, events=None):
        self.raw = json.dumps({"answer": answer})
        self.wait_for, self.events = wait_for, events if events is not None else []
        self.waited_ok = None

    def complete_json(self, system, user, schema, **kw):
        return self.raw

    def stream_json(self, system, user, schema, **kw):
        for i in range(0, len(self.raw), 5):
            piece = self.raw[i:i + 5]
            self.events.append(f"wrote {piece}")
            if self.wait_for is not None and "Second" in self.raw[:i + 5] and self.waited_ok is None:
                # Don't write the rest until the first sentence has been said.
                self.waited_ok = self.wait_for.wait(3)
            yield piece


class EventSpeaker(FakeSpeaker):
    def __init__(self, events, on_say=None):
        super().__init__()
        self.events, self.on_say = events, on_say

    def say(self, text, block=True):
        self.events.append(f"said {text}")
        super().say(text, block)
        if self.on_say:
            self.on_say(text)


def streaming_app(world, monkeypatch, llm, *texts, on_say=None):
    from red.tools.assistant import Answer
    world["registry"].add(Answer(llm))
    world["llm"].replies["Tell me about Everest."] = {"tool": "answer",
                                                       "args": {"question": "Tell me about Everest."}}
    app, speaker, overlay, record, out = follow_app(world, monkeypatch, "Tell me about Everest.", *texts)
    events = llm.events
    app.voice.speaker = EventSpeaker(events, on_say)
    return app, app.voice.speaker, overlay, record


ANSWER = "First sentence here. Second sentence here. Third one."


def test_an_answer_is_spoken_while_the_model_is_still_writing(world, monkeypatch, caplog):
    said_first = threading.Event()
    llm = StreamingLLM(ANSWER, wait_for=said_first)
    app, speaker, overlay, record = streaming_app(
        world, monkeypatch, llm, on_say=lambda t: t.startswith("First") and said_first.set())
    with caplog.at_level("INFO"):
        app.handle("wakeword")
    assert llm.waited_ok is True                    # sentence 1 was spoken before sentence 2 was written
    assert speaker.said == ["First sentence here.", "Second sentence here.", "Third one.",
                            "Anything more you want to know about it?"]
    assert any("first word at" in r.getMessage() for r in caplog.records)
    assert len(record.calls) == 2                    # then it listens for more


def test_the_log_and_memory_have_the_whole_answer(world, monkeypatch):
    llm = StreamingLLM(ANSWER)
    app, speaker, overlay, record = streaming_app(world, monkeypatch, llm)
    app.handle("wakeword")
    entry = log_lines(world)[-1]
    assert entry["result"] == ANSWER and entry["tool"] == "answer"
    assert "Third one." in app.chat.history(4) and "Anything more" not in app.chat.history(4)


def test_hey_red_while_talking_stops_and_listens(world, monkeypatch):
    llm = StreamingLLM(ANSWER)
    holder = {}

    def cut_in(text):
        if text.startswith("First"):
            holder["app"].interrupt()                # as the listener would on "Hey Red"
    app, speaker, overlay, record = streaming_app(world, monkeypatch, llm, "Open my downloads.",
                                                  on_say=cut_in)
    holder["app"] = app
    app.start_listener()
    app.handle("wakeword")
    assert speaker.said[0] == "First sentence here."
    assert "Third one." not in speaker.said and "Anything more you want to know about it?" not in speaker.said
    assert speaker.said[-1] == "Opening Downloads."   # it listened, and ran the next command
    assert app.listener.interrupt_calls[:2] == [True, False]


def test_interrupt_does_nothing_when_red_isnt_talking(world):
    app, speaker, *_ = make_app(world)
    app.interrupt()
    assert app._interrupted is False and not speaker.stopped
