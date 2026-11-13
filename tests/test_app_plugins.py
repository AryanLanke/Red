"""Spotify, WhatsApp and Discord plugins (plan.md B3.2-4): fake desk, no app opens, no key is pressed."""

import sys
from types import SimpleNamespace

import pytest

from red import plugins as pl
from red.executor import Executor
from red.router import Route
from red.tools.base import ToolError, ToolRegistry


@pytest.fixture(scope="module")
def mods():
    loaded = {p.name: p for p in pl.load(None, builtin_dir=pl.BUILTIN_DIR)}
    for name in ("spotify", "whatsapp", "discord"):
        assert not loaded[name].error, loaded[name].error
    return {n: sys.modules[f"red_plugin_{n}"] for n in ("spotify", "whatsapp", "discord")}


class Desk:
    def __init__(self, front=True, foreground="whatsapp.exe"):
        self.log, self.front, self.foreground = [], front, foreground

    def open_uri(self, uri):
        self.log.append(("open", uri))

    def front_app(self, exes, wait=8.0, title=""):
        self.log.append(("front",))
        return self.front

    def foreground_exe(self):
        return self.foreground

    def press(self, combo):
        self.log.append(("press", combo))


def test_spotify_search_quotes_the_query(mods):
    desk = Desk()
    tool = mods["spotify"].SpotifySearch(desk)
    assert tool.run(query="Coldplay & more/../x") == "Searching Spotify for Coldplay & more/../x."
    assert desk.log == [("open", "spotify:search:Coldplay%20%26%20more%2F..%2Fx")]


def test_whats_playing(mods):
    win = lambda title, exe="spotify.exe": SimpleNamespace(exe=exe, title=title)  # noqa: E731
    tool = lambda *ws: mods["spotify"].WhatsPlaying(lambda: list(ws))  # noqa: E731
    assert tool(win("Coldplay - Yellow")).run() == "Yellow by Coldplay."
    assert "nothing is playing" in tool(win("Spotify Free")).run()
    with pytest.raises(ToolError, match="isn't open"):
        tool(win("Coldplay - Yellow", "chrome.exe")).run()


@pytest.fixture
def wa(mods, monkeypatch):
    monkeypatch.setattr(mods["whatsapp"].WhatsAppMessage, "phones",
                        staticmethod(lambda: {"rahul": "919876543210"}))
    return mods["whatsapp"]


def test_whatsapp_reads_back_then_sends(wa):
    desk, asked = Desk(), []
    tool = wa.WhatsAppMessage(desk)
    ex = Executor(ToolRegistry([tool]), ask=lambda q, t: asked.append(q) or "yes")
    reply = ex.execute("x", Route("whatsapp_message", {"to": "Rahul", "text": "running late & sorry"}, True))
    assert asked == ['Send Rahul this on WhatsApp: "running late & sorry"?'] and reply == "Sent to Rahul."
    assert desk.log[0] == ("open", "whatsapp://send?phone=919876543210&text=running%20late%20%26%20sorry")
    assert desk.log[-1] == ("press", "enter")


def test_open_whatsapp(wa):
    desk = Desk()
    assert wa.OpenWhatsApp(desk).run() == "Opening WhatsApp." and desk.log == [("open", "whatsapp://")]


def test_spotify_search_skips_the_fast_path_web_search():
    from red.fastpath import match
    assert match("search Spotify for Coldplay") is None


def test_whatsapp_no_means_nothing_opens(wa):
    desk = Desk()
    ex = Executor(ToolRegistry([wa.WhatsAppMessage(desk)]), ask=lambda q, t: "no")
    assert ex.execute("x", Route("whatsapp_message", {"to": "Rahul", "text": "hi"}, True)) == "Cancelled."
    assert desk.log == []


def test_whatsapp_unknown_contact_never_asks(wa):
    asked, desk = [], Desk()
    ex = Executor(ToolRegistry([wa.WhatsAppMessage(desk)]), ask=lambda q, t: asked.append(q) or "yes")
    assert "[phones]" in ex.execute("x", Route("whatsapp_message", {"to": "Bob", "text": "hi"}, True))
    assert asked == [] and desk.log == []


def test_whatsapp_presses_enter_only_when_in_front(wa):
    desk = Desk(foreground="chrome.exe")
    assert "didn't press Enter" in wa.WhatsAppMessage(desk).run(to="rahul", text="hi")
    assert ("press", "enter") not in desk.log


def test_load_phones(wa, tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('[contacts]\nmom = "m@x.com"\n[phones]\nRahul = "+91 98765-43210"\nbad = "abc"\n')
    assert wa.load_phones(f) == {"rahul": "919876543210"}


@pytest.fixture
def dc(mods, monkeypatch):
    cfg = {"mute_key": "ctrl+shift+m", "channels": {"friends": "discord://-/channels/1/2",
                                                      "evil": "https://evil.example"}}
    monkeypatch.setattr(mods["discord"]._Discord, "config", staticmethod(lambda: cfg))
    return mods["discord"]


def test_discord_opens_only_saved_discord_links(dc):
    desk = Desk()
    tool = dc.OpenDiscord(desk)
    assert tool.run() == "Opening Discord." and desk.log[0] == ("open", "discord://-/channels/@me")
    tool.run(where="Friends")
    assert desk.log[1] == ("open", "discord://-/channels/1/2")
    for bad in ("evil", "nowhere"):
        with pytest.raises(ToolError, match="saved"):
            tool.run(where=bad)
    assert len(desk.log) == 2


def test_discord_mute_uses_your_keybind_in_front_only(dc, monkeypatch):
    desk = Desk(foreground="discord.exe")
    assert "Toggled" in dc.DiscordVoice(desk).run(action="mute")
    assert desk.log == [("press", "ctrl+shift+m")]
    desk = Desk(foreground="chrome.exe")
    monkeypatch.setattr(dc.time, "sleep", lambda s: None)
    with pytest.raises(ToolError, match="didn't press anything"):
        dc.DiscordVoice(desk).run(action="mute")
    assert not any(x[0] == "press" for x in desk.log)
    with pytest.raises(ToolError, match="deafen_key"):
        dc.DiscordVoice(Desk(foreground="discord.exe")).run(action="deafen")


def test_no_messages_are_read_or_sent_by_discord(dc):
    names = {t.name for t in (dc.OpenDiscord(), dc.DiscordVoice())}
    assert not any("message" in n or "send" in n or "read" in n for n in names)
