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


class FakeOverlay:
    def __init__(self):
        self.states = []

    def set_state(self, state, text=""):
        self.states.append((state, text))

    @property
    def names(self):
        return [s for s, _ in self.states]


class FakePlayer:
    def __init__(self, playing=True):
        self.current = Path("song.mp3") if playing else None
        self.paused = False
        self.calls = []

    def pause(self):
        self.calls.append("pause")
        self.paused = True
        return True

    def resume(self):
        self.calls.append("resume")
        self.paused = False
        return True


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
                 "RED_WHISPER_MODEL", "RED_PIPER_VOICE", "RED_MIC_DEVICE", "RED_MUSIC_DIR",
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
             player=None, transcriber=None, fail_wakeword=False, settings=None,
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
                       music_player=lambda: player, log_path=world["home"] / "commands.jsonl",
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
    world["llm"].replies["Hmm."] = LLMError("server down")
    app, speaker, _, _, _ = make_app(world, "Hmm.", "Banana.")
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


def test_music_paused_while_listening_and_resumed(world):
    player = FakePlayer()
    app, *_ = make_app(world, "Open my downloads.", player=player)
    app.handle("hotkey")
    assert player.calls == ["pause", "resume"]


def test_music_not_resumed_after_a_music_command(world):
    player = FakePlayer()
    app, *_ = make_app(world, "Stop the music.", player=player)
    app.handle("hotkey")
    assert player.calls == ["pause"]


def test_no_music_playing_is_left_alone(world):
    player = FakePlayer(playing=False)
    app, *_ = make_app(world, "Open my downloads.", player=player)
    app.handle("hotkey")
    assert player.calls == []


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


class FakePauseMusic(Tool):
    name = "pause_music"
    description = "Pause music"
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, player):
        self.player = player

    def run(self):
        if self.player.pause():
            return "Paused."
        return "The music is already paused."


def test_pause_music_command_pauses_for_real(world):
    player = FakePlayer()
    world["registry"].add(FakePauseMusic(player))
    world["llm"].replies["Pause the music."] = {"tool": "pause_music", "args": {}}
    app, speaker, *_ = make_app(world, "Pause the music.", player=player)
    app.handle("hotkey")
    assert speaker.said == ["Paused."]
    assert player.calls == ["pause", "resume", "pause"] and player.paused


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
