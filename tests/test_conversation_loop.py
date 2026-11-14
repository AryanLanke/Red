"""Conversation mode in the voice loop (red.__main__.VoiceApp), with fakes: no mic, speakers or hotkey."""

import pytest

from red import events
from red.config import load_settings
from test_voice_app import (Audio, FakeListener, FakeOverlay, FakeSpeaker, FakeTranscriber, follow_app,  # noqa: F401
                            make_app, world)   # world is a fixture


@pytest.fixture(autouse=True)
def _clean_events():
    events.clear()
    yield
    events.clear()


class Script:
    """A fake recorder: each call returns audio (a sentence) or empty (silence), then runs an optional hook."""

    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        item = self.items.pop(0) if self.items else None
        if callable(item):
            item = item()
        return Audio(16000 if item == "speech" else 0)


def conv_app(world, monkeypatch, texts, script, **kw):
    monkeypatch.setenv("RED_FOLLOW_UP_SECONDS", "10")
    monkeypatch.setenv("RED_CONVERSATION_IDLE", "60")
    app, speaker, overlay, asked, out = make_app(world, *texts, settings=load_settings(world["home"]), **kw)
    app.voice.record = script
    app.conversation._sound = None
    return app, speaker, overlay, out


def test_conversation_mode_answers_every_sentence_without_the_wake_word(world, monkeypatch):
    got = []
    events.on("conversation", lambda **kw: got.append(kw))
    script = Script("speech", "speech", "speech", None)
    app, speaker, overlay, out = conv_app(world, monkeypatch,
                                          ["Open my downloads.", "Banana.", "Open my downloads."], script)
    app.handle("conversation")
    assert speaker.said[0] == "Opening Downloads."
    assert len(script.calls) >= 3
    assert got[0] == {"on": True, "reason": "button"}
    assert app.conversation.zipped and not app.conversation.active


def test_a_zip_phrase_ends_it_with_no_words(world, monkeypatch):
    script = Script("speech", "speech")
    app, speaker, overlay, out = conv_app(world, monkeypatch, ["Open my downloads.", "Zip it."], script)
    app.handle("conversation")
    assert speaker.said == ["Opening Downloads."]          # nothing said for "zip it"
    assert app.conversation.zipped and not app.conversation.active
    assert len(script.calls) == 2


def test_not_for_me_is_let_go_quietly_and_conversation_goes_on(world, monkeypatch):
    got = []
    events.on("not_for_me", lambda **kw: got.append(kw))
    script = Script("speech", "speech", "speech")
    app, speaker, overlay, out = conv_app(
        world, monkeypatch, ["Claude, make the button blue.", "Open my downloads.", "Zip it."], script)
    app.handle("conversation")
    assert speaker.said == ["Opening Downloads."]
    assert got and got[0]["reason"] == "for claude"


def test_its_own_echo_is_ignored(world, monkeypatch):
    script = Script("speech", "speech")
    app, speaker, overlay, out = conv_app(
        world, monkeypatch, ["Only if you promise to stop being dramatic first.", "Zip it."], script)
    app._last_said = "Only if you promise to stop being dramatic about it first."
    app.handle("conversation")
    assert speaker.said == []                              # the echo got no answer


def test_the_mic_button_while_listening_zips(world, monkeypatch):
    app, speaker, overlay, out = conv_app(world, monkeypatch, [], Script())

    def click():
        assert app.toggle_conversation("button") is False
        return None
    app.voice.record = Script(click)
    app._recording = True
    app.handle("conversation")
    assert app.conversation.zipped and not app.conversation.active


def test_the_button_starts_conversation_mode_through_the_listener(world, monkeypatch):
    app, speaker, overlay, out = conv_app(world, monkeypatch, [], Script())
    started = []

    class L(FakeListener):
        def trigger(self, source):
            started.append(source)
            return True
    app.listener = L(app.handle, "<ctrl>+<alt>+r")
    assert app.toggle_conversation("button") is True and started == ["conversation"]


def test_hey_red_unzips(world, monkeypatch):
    script = Script("speech", None)
    app, speaker, overlay, out = conv_app(world, monkeypatch, ["Open my downloads."], script)
    app.conversation.zip("said")
    app.handle("wakeword")
    assert not app.conversation.zipped
    assert speaker.said == ["Opening Downloads."]


def test_a_follow_up_after_an_action_is_not_lost(world, monkeypatch):
    # The user's complaint: after Red answered, what they said next was dropped.
    script = Script("speech", "speech", None)
    app, speaker, overlay, out = conv_app(world, monkeypatch, ["Open my downloads.", "Banana."], script)
    app.handle("wakeword")
    assert len(speaker.said) == 2 and len(script.calls) == 3
    assert script.calls[1]["start_timeout"] == 10.0


def test_waking_by_a_companion_name_switches_to_it(world, monkeypatch):
    from red import companions
    script = Script("speech", None)
    app, speaker, overlay, out = conv_app(world, monkeypatch, ["Open my downloads."], script)
    switched = []
    monkeypatch.setattr(companions, "set_active", lambda cid, home=None: switched.append(cid))
    monkeypatch.setattr(companions, "active_id", lambda home=None: "red")
    app.listener = FakeListener(app.handle, "<ctrl>+<alt>+r")
    app.listener.wake_name = "asha"
    app.listener.take_wake_audio = lambda: None
    app.handle("wakeword")
    assert switched == ["asha"]
