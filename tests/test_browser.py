"""red.browser and the browser choice in open_url and web_search. No browser starts."""

import pytest

from fakes import FakePopen
from red import browser as b
from red.config import load_settings
from red.router import Router
from red.tools import ToolRegistry
from red.tools.base import ToolError
from red.tools.web import OpenUrl, WebSearch

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class DefaultOpen:
    """The Windows default browser (webbrowser.open)."""

    def __init__(self, ok=True):
        self.ok, self.urls = ok, []

    def __call__(self, url):
        self.urls.append(url)
        return self.ok


def browsers(installed=None, setting="chrome", popen=None, default=None):
    installed = {"chrome.exe": CHROME, "msedge.exe": EDGE} if installed is None else installed
    return b.Browsers(default_open=default or DefaultOpen(), read=installed.get,
                      exists=lambda p: True, popen=popen or FakePopen(), setting=lambda: setting)


# --- picking a browser ------------------------------------------------------------

def test_the_setting_picks_chrome_by_default():
    choice = browsers().pick()
    assert (choice.key, choice.path, choice.exe, choice.name) == ("chrome", CHROME, "chrome.exe", "Chrome")


def test_the_users_words_win_over_the_setting():
    assert browsers(setting="chrome").pick("edge").path == EDGE
    assert browsers(setting="edge").pick(None).path == EDGE


def test_a_browser_that_isnt_installed_means_the_windows_default():
    choice = browsers(installed={}).pick("firefox")
    assert choice.path is None and choice.exe is None and choice.name == "your browser"


def test_default_setting_means_the_windows_default():
    assert browsers(setting="default").pick().path is None


def test_store_builds_and_missing_files_use_the_windows_default():
    store = {"chrome.exe": r"C:\Program Files\WindowsApps\Chrome\chrome.exe"}
    assert browsers(installed=store).pick().path is None
    gone = b.Browsers(read={"chrome.exe": CHROME}.get, exists=lambda p: False, setting=lambda: "chrome")
    assert gone.pick().path is None


def test_red_browser_setting(monkeypatch):
    for value, want in (("EDGE", "edge"), ("default", "default"), ("", "chrome"), ("opera", "chrome")):
        monkeypatch.setenv("RED_BROWSER", value)
        assert b.configured() == want


def test_settings_have_the_browser(monkeypatch, tmp_path):
    monkeypatch.delenv("RED_BROWSER", raising=False)
    assert load_settings(tmp_path).browser == "chrome"
    monkeypatch.setenv("RED_BROWSER", "Firefox")
    assert load_settings(tmp_path).browser == "firefox"
    monkeypatch.setenv("RED_BROWSER", "netscape")
    assert load_settings(tmp_path).browser == "chrome"


# --- starting it -----------------------------------------------------------------

def test_the_url_is_the_only_argument_and_no_shell():
    popen, default = FakePopen(), DefaultOpen()
    web = browsers(popen=popen, default=default)
    assert web.open("https://www.youtube.com", web.pick()) is True
    (argv, kwargs), = popen.calls
    assert argv == [CHROME, "https://www.youtube.com"]
    assert kwargs["shell"] is False and default.urls == []


def test_without_the_browser_the_windows_default_opens_it():
    popen, default = FakePopen(), DefaultOpen()
    web = browsers(installed={}, popen=popen, default=default)
    assert web.open("https://www.youtube.com", web.pick()) is True
    assert popen.calls == [] and default.urls == ["https://www.youtube.com"]


def test_a_browser_that_wont_start_falls_back_to_the_default():
    default = DefaultOpen()
    web = browsers(popen=FakePopen(error=OSError("blocked")), default=default)
    assert web.open("https://example.com", web.pick()) is True
    assert default.urls == ["https://example.com"]


@pytest.mark.parametrize("url", [
    "--gpu-launcher=calc.exe", "file:///C:/Windows", "javascript:alert(1)",
    'https://e.com/" --renderer-cmd-prefix=calc', "https://e.com/a b", "https://e.com/\x00",
])
def test_nothing_but_a_plain_web_address_reaches_the_command_line(url):
    popen = FakePopen()
    web = browsers(popen=popen)
    with pytest.raises(ValueError):
        web.open(url, web.pick())
    assert popen.calls == []


# --- the tools ---------------------------------------------------------------------

def test_open_youtube_opens_it_in_chrome():
    popen = FakePopen()
    tool = OpenUrl(browsers=browsers(popen=popen))
    assert tool.run(url="https://www.youtube.com") == "Opening youtube.com."
    assert popen.calls[0][0] == [CHROME, "https://www.youtube.com"]


def test_open_youtube_from_edge():
    popen = FakePopen()
    tool = OpenUrl(browsers=browsers(popen=popen))
    assert tool.run(url="https://www.youtube.com", browser="edge") == "Opening youtube.com in Edge."
    assert popen.calls[0][0] == [EDGE, "https://www.youtube.com"]


def test_a_named_browser_that_isnt_installed_says_so():
    default = DefaultOpen()
    tool = OpenUrl(browsers=browsers(installed={}, default=default))
    assert tool.run(url="https://www.youtube.com", browser="firefox") == (
        "Firefox isn't installed, so I opened youtube.com in your default browser.")
    assert default.urls == ["https://www.youtube.com"]


def test_open_url_refuses_quotes():
    with pytest.raises(ToolError):
        OpenUrl(browsers=browsers()).run(url='https://e.com/"x')


def test_search_in_edge():
    popen = FakePopen()
    tool = WebSearch(browsers=browsers(popen=popen), engine=lambda: "google")
    assert tool.run(query="lofi", browser="edge") == "Searching the web for lofi in Edge."
    assert popen.calls[0][0] == [EDGE, "https://www.google.com/search?q=lofi"]


def test_search_with_the_setting_says_no_browser():
    tool = WebSearch(browsers=browsers(), engine=lambda: "google")
    assert tool.run(query="lofi", site="youtube") == "Searching YouTube for lofi."


def test_the_browser_argument_is_checked():
    router = Router(ToolRegistry([OpenUrl(browsers=browsers()), WebSearch(browsers=browsers())]))
    router.parse('{"tool": "open_url", "args": {"url": "https://www.youtube.com", "browser": "chrome"}}')
    router.parse('{"tool": "web_search", "args": {"query": "lofi", "browser": "edge"}}')
    from red.router import RouteError
    for bad in ('{"tool": "open_url", "args": {"url": "https://a.com", "browser": "C:/evil.exe"}}',
                '{"tool": "web_search", "args": {"query": "x", "browser": "default"}}'):
        with pytest.raises(RouteError):
            router.parse(bad)


# --- the user's words decide the browser --------------------------------------------

@pytest.mark.parametrize("said, asked, want", [
    ("open YouTube", "chrome", None),                       # the model added it: ignored
    ("open YouTube from Chrome", None, "chrome"),           # the model missed it: added
    ("Can you open YouTube for me from Google Chrome?", "chrome", "chrome"),
    ("Red you just open chrome. I told you to open YouTube", None, "chrome"),
    ("search lofi in Edge", "edge", "edge"),
    ("search lofi in microsoft edge", None, "edge"),
    ("play the edge of tomorrow trailer", "edge", None),    # not a browser here
    ("open YouTube in Edge, not Chrome", "edge", "edge"),
    ("open YouTube in Edge, not Chrome", None, None),       # two named, model unsure
    ("open youtube using firefox", "firefox", "firefox"),
    (None, "edge", "edge"),                                 # words unknown: trust the call
    (None, None, None),
])
def test_from_words(said, asked, want):
    assert b.from_words(said, asked) == want


def test_the_tool_uses_the_users_words_once():
    popen = FakePopen()
    tool = OpenUrl(browsers=browsers(setting="edge", popen=popen))
    tool.set_command("open YouTube")
    assert tool.run(url="https://www.youtube.com", browser="chrome") == "Opening youtube.com."
    assert popen.calls[0][0][0] == EDGE                      # the setting, not the model's guess
    tool.set_command("Can you open YouTube for me from Chrome?")
    assert tool.run(url="https://www.youtube.com") == "Opening youtube.com in Chrome."
    assert popen.calls[1][0][0] == CHROME
