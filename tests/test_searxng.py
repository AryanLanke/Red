"""Red's own SearXNG: install, Windows fix, start and stop. No network, no processes."""

import zipfile

import pytest

from red import searxng
from red.config import load_settings
from red.searxng import (COMMIT, SearxngError, WebSearch, extract_needed, install, installed,
                         patch_for_windows, start, write_settings)

TOP = f"searxng-{COMMIT}/"
ORIGINAL_VALKEYDB = '''"""docs"""

import os
import pwd
import logging
import warnings


def initialize():
    try:
        pass
    except Exception:
        _CLIENT = None
        _pw = pwd.getpwuid(os.getuid())
        logger.exception("[%s (%s)] can't connect valkey DB ...", _pw.pw_name, _pw.pw_uid)
    return False
'''


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("RED_WEB_SEARCH", "RED_SEARCH_URL", "RED_HOME"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path):
    s = load_settings(tmp_path)
    s.ensure_dirs()
    return s


def make_archive(path, extra=()):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(TOP + "searx/__init__.py", "")
        zf.writestr(TOP + "searx/valkeydb.py", ORIGINAL_VALKEYDB)
        zf.writestr(TOP + "searx/engines/brave.py", "")
        zf.writestr(TOP + "requirements.txt", "flask==3.1.3\n")
        zf.writestr(TOP + "LICENSE", "GNU AFFERO GENERAL PUBLIC LICENSE")
        zf.writestr(TOP + "utils/templates/etc/uwsgi/searxng.ini:socket", "")   # Windows can't make this
        zf.writestr(TOP + "docs/index.rst", "")
        for name, text in extra:
            zf.writestr(name, text)
    return path


# --- settings ------------------------------------------------------------------------

def test_web_search_is_on_by_default(tmp_path):
    s = load_settings(tmp_path)
    assert s.web_search is True and s.search_url is None


@pytest.mark.parametrize("value, on", [("off", False), ("no", False), ("on", True), ("1", True)])
def test_web_search_switch(monkeypatch, tmp_path, value, on):
    monkeypatch.setenv("RED_WEB_SEARCH", value)
    assert load_settings(tmp_path).web_search is on


def test_web_search_switch_rejects_nonsense(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_WEB_SEARCH", "maybe")
    with pytest.raises(ValueError, match="RED_WEB_SEARCH"):
        load_settings(tmp_path)


def test_search_url_is_a_setting(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_SEARCH_URL", "http://127.0.0.1:8888")
    assert load_settings(tmp_path).search_url == "http://127.0.0.1:8888"


# --- unpacking and the Windows fix --------------------------------------------------------

def test_only_what_searxng_needs_is_unpacked(tmp_path):
    target = tmp_path / "src"
    extract_needed(make_archive(tmp_path / "a.zip"), target)
    files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    assert files == ["LICENSE", "requirements.txt", "searx/__init__.py",
                     "searx/engines/brave.py", "searx/valkeydb.py"]


def test_unpacking_refuses_paths_that_escape(tmp_path):
    archive = make_archive(tmp_path / "a.zip", extra=[(TOP + "searx/../../../evil.py", "x")])
    with pytest.raises(SearxngError, match="unsafe path"):
        extract_needed(archive, tmp_path / "src")
    assert not (tmp_path / "evil.py").exists()


def test_windows_fix_makes_pwd_optional_and_can_run_twice(tmp_path):
    (tmp_path / "searx").mkdir()
    path = tmp_path / "searx" / "valkeydb.py"
    path.write_text(ORIGINAL_VALKEYDB, encoding="utf-8")
    patch_for_windows(tmp_path)
    fixed = path.read_text(encoding="utf-8")
    assert "\nimport pwd\n" not in fixed and "except ImportError" in fixed
    assert "if pwd is not None:" in fixed
    compile(fixed, "valkeydb.py", "exec")             # still valid Python
    patch_for_windows(tmp_path)                         # already fixed: unchanged
    assert path.read_text(encoding="utf-8") == fixed


def test_windows_fix_refuses_code_it_does_not_know(tmp_path):
    (tmp_path / "searx").mkdir()
    (tmp_path / "searx" / "valkeydb.py").write_text("import os\n", encoding="utf-8")
    with pytest.raises(SearxngError, match="changed"):
        patch_for_windows(tmp_path)


def test_settings_listen_on_this_pc_only_with_a_new_secret_each_time(tmp_path):
    a, b = tmp_path / "a.yml", tmp_path / "b.yml"
    write_settings(a)
    write_settings(b)
    text = a.read_text(encoding="utf-8")
    assert 'bind_address: "127.0.0.1"' in text and "- json" in text and "limiter: false" in text
    assert text != b.read_text(encoding="utf-8")       # the secrets differ
    assert "ultrasecretkey" not in text


# --- install ---------------------------------------------------------------------------------

class FakeRun:
    def __init__(self, settings):
        self.settings, self.calls = settings, []

    def __call__(self, cmd, check, env=None):
        self.calls.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:                   # make the venv's python appear
            python = searxng._venv_python(self.settings)
            python.parent.mkdir(parents=True)
            python.write_text("")


def fake_fetch(tmp_path):
    def fetch(url, dest, sha256, label):
        assert url == searxng.ARCHIVE_URL and sha256 == searxng.ARCHIVE_SHA256
        dest.parent.mkdir(parents=True, exist_ok=True)
        make_archive(dest)
        return dest
    return fetch


def test_install_downloads_unpacks_fixes_and_makes_a_venv(settings, tmp_path):
    run = FakeRun(settings)
    said = []
    install(settings, fetch=fake_fetch(tmp_path), run=run, python="py.exe", say=said.append)
    assert installed(settings)
    assert run.calls[0] == ["py.exe", "-m", "venv", str(searxng.install_dir(settings) / "venv")]
    pip = run.calls[1]
    assert pip[1:4] == ["-m", "pip", "install"] and pip[-1].endswith("requirements.txt")
    assert "except ImportError" in (searxng._src(settings) / "searx" / "valkeydb.py").read_text()
    assert searxng._settings_file(settings).is_file()
    assert said[-1].startswith("Web search is installed")


def test_install_twice_does_nothing_the_second_time(settings, tmp_path):
    install(settings, fetch=fake_fetch(tmp_path), run=FakeRun(settings), say=lambda s: None)
    run = FakeRun(settings)
    install(settings, fetch=fake_fetch(tmp_path), run=run, say=lambda s: None)
    assert run.calls == []


def test_a_half_finished_install_is_started_again_cleanly(settings, tmp_path):
    folder = searxng.install_dir(settings)
    (folder / "src").mkdir(parents=True)
    (folder / "src" / "leftover.txt").write_text("old")
    install(settings, fetch=fake_fetch(tmp_path), run=FakeRun(settings), say=lambda s: None)
    assert not (folder / "src" / "leftover.txt").exists() and installed(settings)


def test_not_installed_without_the_marker(settings):
    assert not installed(settings)


# --- starting it -------------------------------------------------------------------------------

class FakeServer:
    instances = []

    def __init__(self, name, cmd, health_url, log_path, env):
        self.name, self.cmd, self.health_url, self.env = name, cmd, health_url, env
        self.started = self.stopped = False
        FakeServer.instances.append(self)

    def start(self, timeout):
        self.started = True

    def stop(self):
        self.stopped = True


def test_start_runs_it_hidden_on_a_free_port_on_this_pc_only(settings):
    url, server = start(settings, server_factory=FakeServer, port=lambda: 50123)
    assert url == "http://127.0.0.1:50123" and server.started
    assert server.cmd[1:] == ["-m", "searx.webapp"] and server.cmd[0].endswith("python.exe")
    assert server.health_url == "http://127.0.0.1:50123/healthz"
    assert server.env["SEARXNG_PORT"] == "50123"
    assert server.env["SEARXNG_BIND_ADDRESS"] == "127.0.0.1"
    assert server.env["SEARXNG_SETTINGS_PATH"].endswith("settings.yml")


def mark_installed(settings):
    python = searxng._venv_python(settings)
    python.parent.mkdir(parents=True)
    python.write_text("")
    searxng._marker(settings).write_text(COMMIT, encoding="utf-8")


class FakeWarmOpener:
    def __init__(self, error=None):
        self.urls, self.error = [], error

    def __call__(self, url, timeout):
        self.urls.append(url)
        if self.error:
            raise self.error
        import io
        return io.BytesIO(b"{}")


def test_web_search_starts_in_the_background_sets_the_address_and_warms_up(settings):
    mark_installed(settings)
    server = FakeServer("searxng", [], "", None, {})
    environ = {}
    warm = FakeWarmOpener()
    web = WebSearch(settings, starter=lambda s: ("http://127.0.0.1:50123", server),
                    environ=environ, opener=warm)
    assert web.begin()
    web.thread.join(5)
    assert environ["RED_SEARCH_URL"] == "http://127.0.0.1:50123"
    assert web.status.startswith("running")
    assert warm.urls == ["http://127.0.0.1:50123/search?q=hello&format=json"]
    web.stop()
    assert server.stopped and "RED_SEARCH_URL" not in environ


def test_a_failed_warm_up_changes_nothing(settings):
    mark_installed(settings)
    server = FakeServer("searxng", [], "", None, {})
    environ = {}
    web = WebSearch(settings, starter=lambda s: ("http://127.0.0.1:50123", server),
                    environ=environ, opener=FakeWarmOpener(error=OSError("engines slow")))
    web.begin()
    web.thread.join(5)
    assert environ["RED_SEARCH_URL"] == "http://127.0.0.1:50123" and web.status.startswith("running")
    web.stop()


def test_web_search_that_fails_leaves_red_on_wikipedia(settings):
    mark_installed(settings)

    def broken(s):
        raise OSError("blocked by Smart App Control")

    environ = {}
    web = WebSearch(settings, starter=broken, environ=environ)
    web.begin()
    web.thread.join(5)
    assert "RED_SEARCH_URL" not in environ and web.status.startswith("failed")
    web.stop()                                            # nothing to stop: no error


def test_web_search_off_or_not_installed_or_own_url_starts_nothing(monkeypatch, settings, tmp_path):
    started = []
    starter = lambda s: started.append(s)                # noqa: E731
    assert not WebSearch(settings, starter=starter, environ={}).begin()       # not installed
    mark_installed(settings)
    assert not WebSearch(settings, starter=starter,
                         environ={"RED_SEARCH_URL": "http://127.0.0.1:9"}).begin()
    monkeypatch.setenv("RED_WEB_SEARCH", "off")
    off = load_settings(tmp_path)
    assert not WebSearch(off, starter=starter, environ={}).begin()
    assert started == []


def test_doctor_says_whether_web_search_is_ready(monkeypatch, settings, tmp_path):
    from red.doctor import FAIL, OK, WARN, check_web_search
    [check] = check_web_search(settings, None)
    assert check.status == WARN and check.fix == "python -m red setup"
    mark_installed(settings)
    assert check_web_search(settings, None)[0].status == OK
    monkeypatch.setenv("RED_WEB_SEARCH", "off")
    [off] = check_web_search(load_settings(tmp_path), None)
    assert off.status == OK and "off" in off.title
    assert all(c.status != FAIL for c in (check, off))


def test_red_quitting_while_it_starts_stops_it(settings):
    mark_installed(settings)
    server = FakeServer("searxng", [], "", None, {})
    environ = {}
    web = WebSearch(settings, starter=lambda s: ("http://127.0.0.1:1", server), environ=environ)
    web.stop()                       # Red quits first...
    web._run()                       # ...then the start finishes
    assert server.stopped and "RED_SEARCH_URL" not in environ
