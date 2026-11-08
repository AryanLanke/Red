"""python -m red doctor with fakes: no Ollama, microphone, speakers or GPU needed."""

import io
import subprocess

import pytest

from red import doctor
from red.config import load_settings
from red.doctor import FAIL, OK, WARN, Check, System


class FakeSD:
    def __init__(self, mic_error=None, no_output=False):
        self.mic_error, self.no_output = mic_error, no_output
        self.opened, self.closed = [], 0

    def query_devices(self, device=None, kind=None):
        if kind == "input" and self.mic_error:
            raise self.mic_error
        if kind == "output" and self.no_output:
            raise ValueError("no output device")
        return {"name": "Test Mic" if kind == "input" else "Test Speakers"}

    def InputStream(self, device=None, channels=1):  # noqa: N802 - sounddevice's name
        self.opened.append(device)
        sd = self

        class Stream:
            def close(self):
                sd.closed += 1

            def start(self):
                raise AssertionError("doctor must never record")
        return Stream()


def system(packages=None, tags=None, gpu="RTX 4050, 6141 MiB", sd=None, env=None):
    present = packages if packages is not None else {
        n for names in doctor.PACKAGES.values() for n in names}

    def http_json(url, timeout):
        if tags is None:
            raise OSError("connection refused")
        return tags

    def run(argv, **kwargs):
        if gpu is None:
            raise FileNotFoundError("nvidia-smi")
        return subprocess.CompletedProcess(argv, 0, stdout=gpu + "\n", stderr="")

    return System(find_spec=lambda n: object() if n in present else None, http_json=http_json,
                  run=run, sounddevice=lambda: sd or FakeSD(), version=(3, 11, 9),
                  platform="win32", environ=env or {"RED_HOME": "x"})


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for name in ("RED_LLM_URL", "RED_LLM_MODEL", "RED_WAKEWORD", "RED_HOTKEY", "RED_MIC_DEVICE",
                 "RED_WHISPER_DEVICE"):
        monkeypatch.delenv(name, raising=False)
    s = load_settings(tmp_path)
    s.ensure_dirs()
    return s


def statuses(checks):
    return [(c.status, c.title) for c in checks]


def test_python_and_platform():
    assert doctor.check_python(system())[0].status == OK
    old = System(version=(3, 10, 4), platform="linux")
    checks = doctor.check_python(old)
    assert [c.status for c in checks] == [FAIL, WARN]


def test_packages_missing_voice_is_a_warning_and_core_a_failure():
    checks = doctor.check_packages(system(packages={"jsonschema", "dotenv", "PySide6", "pygame"}))
    assert [c.status for c in checks] == [OK, WARN, OK]
    assert "--typed" in checks[1].title and "pip install" in checks[1].fix
    checks = doctor.check_packages(system(packages=set()))
    assert checks[0].status == FAIL


def test_home(settings):
    checks = doctor.check_home(settings, system())
    assert checks[0].status == OK and "from RED_HOME" in checks[0].title
    assert checks[1].status == WARN and ".env" in checks[1].fix
    (settings.config_dir / ".env").write_text("", encoding="utf-8")
    assert len(doctor.check_home(settings, system())) == 1


def test_llm_running_with_and_without_model(settings):
    tag = "qwen2.5:7b-instruct-q4_K_M"
    ok = doctor.check_llm(settings, system(tags={"models": [{"name": tag}]}))
    assert ok[0].status == OK
    missing = doctor.check_llm(settings, system(tags={"models": [{"name": "other"}]}))
    assert missing[0].status == FAIL and "setup" in missing[0].fix


def test_llm_not_running_uses_installed_files(settings):
    from red.llm import OLLAMA_VERSION
    checks = doctor.check_llm(settings, system(tags=None))
    assert checks[0].status == FAIL and "Ollama" in checks[0].title
    marker = settings.bin_dir / "ollama" / OLLAMA_VERSION / ".installed"
    marker.parent.mkdir(parents=True)
    marker.write_text("x")
    manifest = (settings.models_dir / "ollama" / "manifests" / "registry.ollama.ai" / "library"
                / "qwen2.5" / "7b-instruct-q4_K_M")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}")
    assert doctor.check_llm(settings, system(tags=None))[0].status == OK


def test_llm_own_server(settings, monkeypatch, tmp_path):
    monkeypatch.setenv("RED_LLM_URL", "http://127.0.0.1:1234/v1")
    s = load_settings(tmp_path)
    assert doctor.check_llm(s, system(tags={"data": []}))[0].status == OK
    assert doctor.check_llm(s, system(tags=None))[0].status == FAIL


def test_gpu(settings):
    assert doctor.check_gpu(settings, system())[0].status == OK
    checks = doctor.check_gpu(settings, system(gpu=None))
    assert checks[0].status == WARN and "3b" in checks[0].fix


def test_audio_opens_but_never_records(settings):
    sd = FakeSD()
    checks = doctor.check_audio(settings, system(sd=sd))
    assert statuses(checks) == [(OK, "Microphone: Test Mic"), (OK, "Speakers: Test Speakers")]
    assert sd.opened == [None] and sd.closed == 1


def test_audio_problems(settings):
    checks = doctor.check_audio(settings, system(sd=FakeSD(mic_error=OSError("denied"),
                                                          no_output=True)))
    assert [c.status for c in checks] == [FAIL, FAIL]
    assert "Privacy" in checks[0].fix

    def no_sd():
        raise ImportError("sounddevice")
    sys_ = system()
    sys_.sounddevice = no_sd
    assert doctor.check_audio(settings, sys_)[0].status == WARN


def test_config_files(settings):
    checks = doctor.check_config_files(settings, system())
    assert [c.status for c in checks] == [WARN, WARN, WARN]
    settings.allowlist_path.write_text("[folders\n", encoding="utf-8")
    settings.repos_path.write_text("[repos]\nred = 'D:\\\\RED\\\\red'\n", encoding="utf-8")
    settings.contacts_path.write_text('[contacts]\nmom = "not an address"\n', encoding="utf-8")
    checks = doctor.check_config_files(settings, system())
    assert [c.status for c in checks] == [FAIL, OK, FAIL]


def test_report_symbols_and_exit_code():
    checks = [Check(OK, "fine"), Check(WARN, "hmm", "do this"), Check(FAIL, "bad", "fix that")]
    class Utf8(io.StringIO):
        encoding = "utf-8"
    out = Utf8()
    assert doctor.report(checks, out) == 1
    text = out.getvalue()
    assert "\u2705 fine" in text and "Fix: fix that" in text and "1 problem(s), 1 warning(s)" in text

    class Cp1252(io.StringIO):
        encoding = "cp1252"
    out = Cp1252()
    assert doctor.report(checks[:2], out) == 0
    assert "[ok]   fine" in out.getvalue() and "[warn] hmm" in out.getvalue()


def test_run_checks_never_crashes_on_a_broken_check(settings, monkeypatch):
    def broken(settings, sys_):
        raise RuntimeError("boom")
    monkeypatch.setattr(doctor, "check_gpu", broken)
    checks = doctor.run_checks(system(packages={"jsonschema", "dotenv"}), settings)
    assert any("couldn't run" in c.title for c in checks)


def test_bad_setting_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    monkeypatch.setenv("RED_WHISPER_DEVICE", "tpu")
    checks = doctor.run_checks(system())
    assert checks[-1].status == FAIL and "RED_WHISPER_DEVICE" in checks[-1].title


def test_cli_doctor_starts_nothing(monkeypatch):
    from red import __main__ as cli

    def no_connect(settings):
        raise AssertionError("doctor must not start the LLM")
    monkeypatch.setattr(cli, "connect", no_connect)
    monkeypatch.setattr(doctor, "main", lambda: 0)
    assert cli.main(["doctor"]) == 0


def test_triggers(settings, monkeypatch, tmp_path):
    pytest.importorskip("numpy")
    monkeypatch.setenv("RED_WAKEWORD", "not_a_real_wake_word")
    monkeypatch.setenv("RED_HOTKEY", "Ctrl+Alt+R")
    s = load_settings(tmp_path)
    checks = doctor.check_triggers(s, system())
    assert statuses(checks)[0] == (OK, "Hotkey Ctrl+Alt+R")
    assert checks[1].status == WARN and "hotkey only" in checks[1].title
    monkeypatch.setenv("RED_HOTKEY", "R")
    assert doctor.check_triggers(load_settings(tmp_path), system())[0].status == FAIL


def test_voice_models_missing(settings):
    pytest.importorskip("faster_whisper")
    checks = doctor.check_voice_models(settings, system())
    assert [c.status for c in checks] == [FAIL, FAIL]
    assert all("setup" in c.fix for c in checks)
